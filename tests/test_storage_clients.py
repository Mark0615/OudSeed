"""Tests for clients, account bindings, and report schedules (SQLite)."""

import pytest

from src.storage.crypto import generate_key
from src.storage.db import build_session_factory, create_all, create_db_engine, session_scope
from src.storage.repository import (
    bind_account,
    create_client,
    create_platform_connection,
    create_report_schedule,
    create_workspace,
    list_client_accounts,
    list_clients,
    list_report_schedules,
    read_schedule_email_to,
    upsert_user_by_google_sub,
)


@pytest.fixture
def session_factory():
    engine = create_db_engine("sqlite://")
    create_all(engine)
    return build_session_factory(engine)


@pytest.fixture
def key():
    return generate_key()


def _workspace(session, *, sub="g-1"):
    owner = upsert_user_by_google_sub(session, google_sub=sub, email=f"{sub}@example.com")
    return create_workspace(session, name="Acme", owner=owner)


def test_create_and_list_clients(session_factory):
    with session_scope(session_factory) as session:
        ws = _workspace(session)
        create_client(session, workspace_id=ws.id, client_key="miniware_tw", name="Miniware TW")
        clients = list_clients(session, ws.id)
        assert [c.client_key for c in clients] == ["miniware_tw"]


def test_bind_meta_and_google_to_one_client(session_factory):
    with session_scope(session_factory) as session:
        ws = _workspace(session)
        client = create_client(session, workspace_id=ws.id, client_key="acme", name="Acme")
        meta = create_platform_connection(
            session, workspace_id=ws.id, platform="meta_ads", external_account_id="act_1"
        )
        google = create_platform_connection(
            session, workspace_id=ws.id, platform="google_ads", external_account_id="123"
        )
        bind_account(session, client=client, connection=meta)
        bind_account(session, client=client, connection=google)

        bindings = list_client_accounts(session, client.id)
        assert len(bindings) == 2


def test_bind_rejects_cross_workspace_connection(session_factory):
    with session_scope(session_factory) as session:
        ws_a = _workspace(session, sub="a")
        ws_b = _workspace(session, sub="b")
        client = create_client(session, workspace_id=ws_a.id, client_key="acme", name="Acme")
        foreign = create_platform_connection(
            session, workspace_id=ws_b.id, platform="meta_ads", external_account_id="act_x"
        )
        with pytest.raises(ValueError, match="workspace"):
            bind_account(session, client=client, connection=foreign)


def test_report_schedule_encrypts_recipient(session_factory, key):
    with session_scope(session_factory) as session:
        ws = _workspace(session)
        client = create_client(session, workspace_id=ws.id, client_key="acme", name="Acme")
        schedule = create_report_schedule(
            session,
            client_id=client.id,
            schedule_key="monthly_email_default",
            report_type="monthly",
            delivery_day="1",
            email_to="buyer@example.com",
            key=key,
            depth="standard",
        )
        sched_id = schedule.id

    with session_scope(session_factory) as session:
        schedules = list_report_schedules(session, client.id)
        assert len(schedules) == 1
        stored = schedules[0]
        assert stored.id == sched_id
        assert "buyer@example.com" not in (stored.encrypted_email_to or "")
        assert read_schedule_email_to(stored, key=key) == "buyer@example.com"


def test_report_schedule_rejects_bad_type_and_depth(session_factory):
    with session_scope(session_factory) as session:
        ws = _workspace(session)
        client = create_client(session, workspace_id=ws.id, client_key="acme", name="Acme")
        with pytest.raises(ValueError, match="report_type"):
            create_report_schedule(
                session,
                client_id=client.id,
                schedule_key="s",
                report_type="daily",
                delivery_day="1",
            )
        with pytest.raises(ValueError, match="depth"):
            create_report_schedule(
                session,
                client_id=client.id,
                schedule_key="s",
                report_type="monthly",
                delivery_day="1",
                depth="ultra",
            )
