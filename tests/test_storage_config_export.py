"""Tests for exporting a workspace to pipeline config (SQLite + in-memory key)."""

import pytest
import yaml

from src.storage.config_export import export_workspace_to_config
from src.storage.crypto import generate_key
from src.storage.db import build_session_factory, create_all, create_db_engine, session_scope
from src.storage.repository import (
    bind_account,
    create_client,
    create_platform_connection,
    create_report_schedule,
    create_workspace,
    store_connection_token,
    upsert_user_by_google_sub,
)
from src.utils.config_loader import load_config_from_yaml


@pytest.fixture
def session_factory():
    engine = create_db_engine("sqlite://")
    create_all(engine)
    return build_session_factory(engine)


@pytest.fixture
def key():
    return generate_key()


def _seed_workspace(session, key):
    """Create a workspace with one client bound to Meta + Google and a schedule."""
    owner = upsert_user_by_google_sub(session, google_sub="g-1", email="o@example.com")
    ws = create_workspace(session, name="Acme", owner=owner)
    client = create_client(session, workspace_id=ws.id, client_key="miniware_tw", name="Miniware TW")

    meta = create_platform_connection(
        session, workspace_id=ws.id, platform="meta_ads",
        external_account_id="act_123", account_name="Miniware Meta",
    )
    store_connection_token(meta, secret="meta-token", key=key)
    google = create_platform_connection(
        session, workspace_id=ws.id, platform="google_ads",
        external_account_id="1234567890", account_name="Miniware Google",
    )
    store_connection_token(google, secret="google-token", key=key)

    bind_account(session, client=client, connection=meta)
    bind_account(session, client=client, connection=google)

    create_report_schedule(
        session, client_id=client.id, schedule_key="monthly_email_default",
        report_type="monthly", delivery_day="1", timezone="Asia/Taipei",
        depth="standard", email_to="buyer@example.com", key=key,
    )
    return ws


def test_export_passes_config_loader_validation(session_factory, key):
    with session_scope(session_factory) as session:
        ws = _seed_workspace(session, key)
        config = export_workspace_to_config(
            session, ws.id, bigquery_project="oudseed",
            bigquery_dataset="ads_pipeline", encryption_key=key,
        )

    # The whole point: the exported config must be pipeline-valid.
    validated = load_config_from_yaml(parsed_config=config)
    assert validated["workspace_id"] == ws.id
    assert len(validated["clients"]) == 1
    client = validated["clients"][0]
    assert client["client_id"] == "miniware_tw"
    assert client["platforms"]["meta_ads"]["accounts"][0]["ad_account_id"] == "act_123"
    assert client["platforms"]["google_ads"]["accounts"][0]["customer_id"] == "1234567890"
    # Monthly delivery day is coerced to int, matching config conventions.
    assert client["report_schedules"][0]["delivery_day"] == 1
    # Recipient email is decrypted on export.
    assert client["report_schedules"][0]["email_to"] == "buyer@example.com"
    assert client["destinations"]["bigquery"]["dataset"] == "ads_pipeline"


def test_export_round_trips_through_yaml(session_factory, key):
    with session_scope(session_factory) as session:
        ws = _seed_workspace(session, key)
        config = export_workspace_to_config(
            session, ws.id, bigquery_project="oudseed",
            bigquery_dataset="ads_pipeline", encryption_key=key,
        )
    # Must serialize to YAML and re-load as valid config (what gets written to file).
    yaml_text = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
    reloaded = load_config_from_yaml(yaml_text=yaml_text)
    assert reloaded["clients"][0]["client_name"] == "Miniware TW"


def test_export_unknown_workspace_raises(session_factory):
    with session_scope(session_factory) as session, pytest.raises(ValueError, match="workspace"):
        export_workspace_to_config(
            session, "nope", bigquery_project="p", bigquery_dataset="d"
        )


def test_export_weekly_keeps_string_delivery_day(session_factory, key):
    with session_scope(session_factory) as session:
        owner = upsert_user_by_google_sub(session, google_sub="g", email="o@example.com")
        ws = create_workspace(session, name="W", owner=owner)
        client = create_client(session, workspace_id=ws.id, client_key="c", name="C")
        create_report_schedule(
            session, client_id=client.id, schedule_key="weekly",
            report_type="weekly", delivery_day="monday",
        )
        config = export_workspace_to_config(
            session, ws.id, bigquery_project="p", bigquery_dataset="d", encryption_key=key,
        )
    assert config["clients"][0]["report_schedules"][0]["delivery_day"] == "monday"
