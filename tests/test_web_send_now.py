"""Tests for the on-demand report send (the dashboard's test-send button).

The heavy generate + send loop is reused from the deployed pipeline (and tested
in test_send_account_reports.py), so here we only verify the web wrapper's
schedule resolution and outcome mapping, with that loop and discovery faked.
"""

from __future__ import annotations

import src.web.send_now as send_now
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
from src.web.send_now import SendNowResult, send_workspace_reports_now


def _config_with_schedule(*, email_to: str | None) -> dict:
    """A minimal exported-config shape with one onboarding schedule."""
    schedule: dict = {
        "schedule_id": "onboarding_email",
        "enabled": True,
        "report_type": "monthly",
        "delivery_day": 1,
        "channel": "email",
        "depth": "standard",
    }
    if email_to:
        schedule["email_to"] = email_to
    return {
        "workspace_id": "ws-1",
        "defaults": {"timezone": "Asia/Taipei"},
        "bigquery": {"project_id": "proj", "dataset": "ds"},
        "clients": [
            {
                "client_id": "acme_tw",
                "client_name": "Acme TW",
                "report_schedules": [schedule],
            }
        ],
    }


def test_send_now_returns_no_recipient_when_email_unset() -> None:
    config = _config_with_schedule(email_to=None)
    result = send_workspace_reports_now(
        config=config,
        destination=object(),
        openai_client=object(),
        sender=object(),
        schedule_id="onboarding_email",
    )
    assert result == SendNowResult("no_recipient")


def test_send_now_returns_no_recipient_when_schedule_missing() -> None:
    config = _config_with_schedule(email_to="buyer@example.com")
    result = send_workspace_reports_now(
        config=config,
        destination=object(),
        openai_client=object(),
        sender=object(),
        schedule_id="does_not_exist",
    )
    assert result.status == "no_recipient"


def test_send_now_returns_no_groups_when_no_data(monkeypatch) -> None:
    config = _config_with_schedule(email_to="buyer@example.com")
    monkeypatch.setattr(send_now, "discover_account_report_groups", lambda **_: [])
    result = send_workspace_reports_now(
        config=config,
        destination=object(),
        openai_client=object(),
        sender=object(),
        schedule_id="onboarding_email",
    )
    assert result == SendNowResult("no_groups")


def test_send_now_sent_passes_schedule_values_to_pipeline(monkeypatch) -> None:
    config = _config_with_schedule(email_to="buyer@example.com")
    groups = [{"account_group_name": "Acme", "account_ids": ["act_1"], "platforms": ["meta_ads"]}]
    monkeypatch.setattr(send_now, "discover_account_report_groups", lambda **_: groups)

    captured: dict = {}

    def fake_send(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(send_now, "_generate_and_send_account_group_reports", fake_send)

    result = send_workspace_reports_now(
        config=config,
        destination=object(),
        openai_client=object(),
        sender=object(),
        schedule_id="onboarding_email",
    )
    assert result == SendNowResult("sent", 1)
    # The saved schedule drives the report: recipient, depth, type, client.
    assert captured["recipient"] == "buyer@example.com"
    assert captured["report_type"] == "monthly"
    assert captured["report_depth"] == "standard"
    assert captured["client_id"] == "acme_tw"
    assert captured["workspace_id"] == "ws-1"


def test_send_now_failure_is_returned_not_raised(monkeypatch) -> None:
    config = _config_with_schedule(email_to="buyer@example.com")
    groups = [{"account_group_name": "Acme", "account_ids": ["act_1"], "platforms": ["meta_ads"]}]
    monkeypatch.setattr(send_now, "discover_account_report_groups", lambda **_: groups)

    def boom(**_):
        raise RuntimeError("SMTP auth failed")

    monkeypatch.setattr(send_now, "_generate_and_send_account_group_reports", boom)

    result = send_workspace_reports_now(
        config=config,
        destination=object(),
        openai_client=object(),
        sender=object(),
        schedule_id="onboarding_email",
    )
    assert result.status == "failed"
    assert result.group_count == 1
    assert "SMTP auth failed" in result.detail


def test_build_workspace_report_config_from_durable_store(tmp_path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'send.db'}")
    create_all(engine)
    session_factory = build_session_factory(engine)
    key = generate_key()

    with session_scope(session_factory) as session:
        owner = upsert_user_by_google_sub(session, google_sub="g-1", email="o@example.com")
        workspace = create_workspace(session, name="Acme", owner=owner)
        client = create_client(
            session, workspace_id=workspace.id, client_key="acme_tw", name="Acme TW"
        )
        meta = create_platform_connection(
            session,
            workspace_id=workspace.id,
            platform="meta_ads",
            external_account_id="act_123",
            account_name="Acme Meta",
        )
        store_connection_token(meta, secret="meta-token", key=key)
        bind_account(session, client=client, connection=meta)
        create_report_schedule(
            session,
            client_id=client.id,
            schedule_key="onboarding_email",
            report_type="monthly",
            delivery_day="1",
            depth="standard",
            email_to="buyer@example.com",
            key=key,
        )
        workspace_id = workspace.id

    with session_scope(session_factory) as session:
        config = send_now.build_workspace_report_config(
            session,
            workspace_id,
            bigquery_project="proj",
            bigquery_dataset="ds",
            encryption_key=key,
        )

    assert config["workspace_id"] == workspace_id
    schedule = config["clients"][0]["report_schedules"][0]
    assert schedule["schedule_id"] == "onboarding_email"
    assert schedule["email_to"] == "buyer@example.com"
