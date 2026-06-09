"""Tests for the scheduled report dispatcher (offline, fake send pipeline)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.ai.dispatch_scheduled_reports import (
    DispatchResult,
    dispatch_due_reports,
    find_due_schedules,
)
from src.ai.workspace_reports import SendNowResult
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

KEY = generate_key()


def _session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'dispatch.db'}")
    create_all(engine)
    return build_session_factory(engine)


def _seed_workspace(
    session,
    *,
    sub: str,
    report_type: str = "monthly",
    delivery_day: str = "1",
    email_to: str | None = "buyer@example.com",
    enabled: bool = True,
    schedule_key: str = "onboarding_email",
):
    owner = upsert_user_by_google_sub(session, google_sub=sub, email=f"{sub}@example.com")
    workspace = create_workspace(session, name=f"WS-{sub}", owner=owner)
    client = create_client(
        session, workspace_id=workspace.id, client_key="default", name="Default"
    )
    meta = create_platform_connection(
        session,
        workspace_id=workspace.id,
        platform="meta_ads",
        external_account_id="act_1",
        account_name="Acme",
    )
    store_connection_token(meta, secret="tok", key=KEY)
    bind_account(session, client=client, connection=meta)
    create_report_schedule(
        session,
        client_id=client.id,
        schedule_key=schedule_key,
        report_type=report_type,
        delivery_day=delivery_day,
        depth="standard",
        email_to=email_to,
        enabled=enabled,
        key=KEY,
    )
    return workspace.id


def test_find_due_schedules_returns_only_due_enabled_with_recipient(tmp_path):
    factory = _session_factory(tmp_path)
    now = datetime(2026, 6, 1, 9, 0, tzinfo=ZoneInfo("Asia/Taipei"))  # day 1
    with session_scope(factory) as session:
        _seed_workspace(session, sub="due", delivery_day="1")  # due today
        _seed_workspace(session, sub="notdue", delivery_day="15")  # not due
        _seed_workspace(session, sub="disabled", delivery_day="1", enabled=False)
        _seed_workspace(session, sub="norecipient", delivery_day="1", email_to=None)

    with session_scope(factory) as session:
        due = find_due_schedules(session, now=now)

    # Only the enabled, recipient-bearing, day-1 schedule is due.
    assert len(due) == 1
    assert due[0].report_type == "monthly"


def test_dispatch_due_reports_sends_each_due_schedule(tmp_path):
    factory = _session_factory(tmp_path)
    now = datetime(2026, 6, 1, 9, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    with session_scope(factory) as session:
        _seed_workspace(session, sub="a", delivery_day="1")
        _seed_workspace(session, sub="b", delivery_day="1")
        _seed_workspace(session, sub="c", delivery_day="9")  # not due

    sent_calls: list = []

    def fake_send(**kwargs):
        sent_calls.append(kwargs["schedule_id"])
        return SendNowResult("sent", 1)

    with session_scope(factory) as session:
        results = dispatch_due_reports(
            session,
            destination=object(),
            openai_client=object(),
            sender=object(),
            bigquery_project="proj",
            bigquery_dataset="ds",
            encryption_key=KEY,
            now=now,
            send=fake_send,
        )

    assert len(results) == 2
    assert all(r.status == "sent" for r in results)
    assert sent_calls == ["onboarding_email", "onboarding_email"]


def test_dispatch_isolates_per_workspace_failures(tmp_path):
    factory = _session_factory(tmp_path)
    now = datetime(2026, 6, 1, 9, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    with session_scope(factory) as session:
        _seed_workspace(session, sub="ok")
        _seed_workspace(session, sub="boom")

    calls = {"n": 0}

    def flaky_send(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("smtp down")
        return SendNowResult("sent", 1)

    with session_scope(factory) as session:
        results = dispatch_due_reports(
            session,
            destination=object(),
            openai_client=object(),
            sender=object(),
            bigquery_project="proj",
            bigquery_dataset="ds",
            encryption_key=KEY,
            now=now,
            send=flaky_send,
        )

    assert len(results) == 2
    statuses = sorted(r.status for r in results)
    assert statuses == ["error", "sent"]
    # The failure is captured as a result, not raised.
    assert DispatchResult("onboarding_email", "error", "RuntimeError") in results
