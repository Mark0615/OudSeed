"""Tests for the daily multi-workspace auto-sync orchestrator (offline)."""

from __future__ import annotations

from dataclasses import dataclass

import src.sync.daily_sync as daily_sync
from src.sync.daily_sync import sync_all_workspaces
from src.web.first_sync import AccountSyncResult, FirstSyncResult


@dataclass
class FakeWorkspace:
    id: str


@dataclass
class FakeConnection:
    platform: str
    external_account_id: str
    status: str = "active"


@dataclass
class FakeClient:
    client_key: str = "default"


def _patch_repo(monkeypatch, *, workspaces, connections_by_ws):
    monkeypatch.setattr(daily_sync, "list_all_workspaces", lambda session: workspaces)
    monkeypatch.setattr(
        daily_sync,
        "list_connections",
        lambda session, ws_id: connections_by_ws.get(ws_id, []),
    )
    monkeypatch.setattr(
        daily_sync, "get_or_create_default_client", lambda session, ws: FakeClient()
    )
    monkeypatch.setattr(
        daily_sync,
        "bind_connections_to_client",
        lambda session, *, client, connections: [],
    )


def _ok_result(connections):
    return FirstSyncResult(
        results=tuple(
            AccountSyncResult(c.platform, c.external_account_id, "success", rows=10)
            for c in connections
        )
    )


def test_syncs_each_workspace_active_accounts(monkeypatch):
    workspaces = [FakeWorkspace("w1"), FakeWorkspace("w2")]
    connections_by_ws = {
        "w1": [FakeConnection("meta_ads", "act_1"), FakeConnection("google_ads", "111")],
        "w2": [FakeConnection("meta_ads", "act_2")],
    }
    _patch_repo(monkeypatch, workspaces=workspaces, connections_by_ws=connections_by_ws)

    seen_windows = []

    def fake_run(**kwargs):
        seen_windows.append((kwargs["start_date"], kwargs["end_date"]))
        return _ok_result(kwargs["connections"])

    results = sync_all_workspaces(
        session=object(),
        destination=object(),
        meta_connector_factory=lambda t: None,
        google_connector_factory=lambda t: None,
        start_date="2026-06-07",
        end_date="2026-06-09",
        run_sync=fake_run,
    )

    assert {r.workspace_id: r.succeeded for r in results} == {"w1": 2, "w2": 1}
    assert all(r.status == "synced" for r in results)
    # Each workspace synced over the same passed-in window.
    assert seen_windows == [("2026-06-07", "2026-06-09"), ("2026-06-07", "2026-06-09")]


def test_skips_workspace_with_no_active_accounts(monkeypatch):
    workspaces = [FakeWorkspace("w1")]
    connections_by_ws = {"w1": [FakeConnection("meta_ads", "act_1", status="revoked")]}
    _patch_repo(monkeypatch, workspaces=workspaces, connections_by_ws=connections_by_ws)

    def fake_run(**kwargs):  # pragma: no cover - must not be called
        raise AssertionError("run_sync should not run when no active accounts")

    results = sync_all_workspaces(
        session=object(),
        destination=object(),
        meta_connector_factory=lambda t: None,
        google_connector_factory=lambda t: None,
        start_date="2026-06-07",
        end_date="2026-06-09",
        run_sync=fake_run,
    )

    assert len(results) == 1
    assert results[0].status == "skipped"
    assert results[0].attempted == 0


def test_isolates_per_workspace_failures(monkeypatch):
    workspaces = [FakeWorkspace("w_bad"), FakeWorkspace("w_ok")]
    connections_by_ws = {
        "w_bad": [FakeConnection("meta_ads", "act_bad")],
        "w_ok": [FakeConnection("meta_ads", "act_ok")],
    }
    _patch_repo(monkeypatch, workspaces=workspaces, connections_by_ws=connections_by_ws)

    def fake_run(**kwargs):
        if kwargs["workspace_id"] == "w_bad":
            raise RuntimeError("warehouse exploded")
        return _ok_result(kwargs["connections"])

    results = sync_all_workspaces(
        session=object(),
        destination=object(),
        meta_connector_factory=lambda t: None,
        google_connector_factory=lambda t: None,
        start_date="2026-06-07",
        end_date="2026-06-09",
        run_sync=fake_run,
    )

    by_ws = {r.workspace_id: r for r in results}
    assert by_ws["w_bad"].status == "error"
    assert by_ws["w_bad"].detail == "RuntimeError"
    assert by_ws["w_ok"].status == "synced"
    assert by_ws["w_ok"].succeeded == 1


def test_records_and_logs_account_level_failures(monkeypatch, capsys):
    """A failing account must be recorded and logged, not silently dropped.

    Regression guard: an expired Meta token once failed every account for weeks
    while the run still summarized as a success.
    """
    workspaces = [FakeWorkspace("w1")]
    connections_by_ws = {
        "w1": [FakeConnection("meta_ads", "act_1234567890"), FakeConnection("google_ads", "111")],
    }
    _patch_repo(monkeypatch, workspaces=workspaces, connections_by_ws=connections_by_ws)

    def fake_run(**kwargs):
        return FirstSyncResult(
            results=(
                AccountSyncResult(
                    "meta_ads", "act_1234567890", "failed", error="Session has expired"
                ),
                AccountSyncResult("google_ads", "111", "success", rows=10),
            )
        )

    results = sync_all_workspaces(
        session=object(),
        destination=object(),
        meta_connector_factory=lambda t: None,
        google_connector_factory=lambda t: None,
        start_date="2026-06-07",
        end_date="2026-06-09",
        run_sync=fake_run,
    )

    result = results[0]
    assert (result.succeeded, result.failed) == (1, 1)
    assert [(f.platform, f.error) for f in result.failures] == [
        ("meta_ads", "Session has expired")
    ]

    out = capsys.readouterr().out
    assert "event=daily_sync_account_failed" in out
    assert "Session has expired" in out
    # The real account id must never reach the log.
    assert "act_1234567890" not in out


def test_truncates_long_account_error(monkeypatch, capsys):
    workspaces = [FakeWorkspace("w1")]
    connections_by_ws = {"w1": [FakeConnection("meta_ads", "act_1")]}
    _patch_repo(monkeypatch, workspaces=workspaces, connections_by_ws=connections_by_ws)

    def fake_run(**kwargs):
        return FirstSyncResult(
            results=(AccountSyncResult("meta_ads", "act_1", "failed", error="x" * 500),)
        )

    results = sync_all_workspaces(
        session=object(),
        destination=object(),
        meta_connector_factory=lambda t: None,
        google_connector_factory=lambda t: None,
        start_date="2026-06-07",
        end_date="2026-06-09",
        run_sync=fake_run,
    )

    assert len(results[0].failures[0].error) == daily_sync.MAX_LOGGED_ERROR_CHARS
