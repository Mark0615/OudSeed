"""Tests for the one-time historical backfill orchestrator (offline)."""

from __future__ import annotations

from dataclasses import dataclass

import src.sync.backfill as backfill
from src.sync.backfill import _start_for, backfill_all
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
    monkeypatch.setattr(backfill, "list_all_workspaces", lambda session: workspaces)
    monkeypatch.setattr(
        backfill,
        "list_connections",
        lambda session, ws_id: connections_by_ws.get(ws_id, []),
    )
    monkeypatch.setattr(
        backfill, "get_or_create_default_client", lambda session, ws: FakeClient()
    )
    monkeypatch.setattr(
        backfill,
        "bind_connections_to_client",
        lambda session, *, client, connections: [],
    )


def _ok(connections):
    return FirstSyncResult(
        results=tuple(
            AccountSyncResult(c.platform, c.external_account_id, "success", rows=5)
            for c in connections
        )
    )


def test_start_for_counts_back_inclusive_days():
    assert _start_for("2026-06-09", 30) == "2026-05-10"


def test_backfills_each_platform_over_its_own_window(monkeypatch):
    workspaces = [FakeWorkspace("w1")]
    connections_by_ws = {
        "w1": [FakeConnection("meta_ads", "act_1"), FakeConnection("google_ads", "111")],
    }
    _patch_repo(monkeypatch, workspaces=workspaces, connections_by_ws=connections_by_ws)

    calls: list[tuple[str, str, str]] = []

    def fake_run(**kwargs):
        platform = kwargs["connections"][0].platform
        calls.append((platform, kwargs["start_date"], kwargs["end_date"]))
        return _ok(kwargs["connections"])

    results = backfill_all(
        session=object(),
        destination=object(),
        meta_connector_factory=lambda t: None,
        google_connector_factory=lambda t: None,
        end_date="2026-03-01",
        # Meta gets a 60-day span (-> 2 windows of 30), Google a 30-day span (1 window).
        platform_starts={"meta_ads": "2026-01-01", "google_ads": "2026-01-31"},
        window_days=30,
        run_sync=fake_run,
    )

    meta_calls = [c for c in calls if c[0] == "meta_ads"]
    google_calls = [c for c in calls if c[0] == "google_ads"]
    assert len(meta_calls) == 2  # 60-day span / 30
    assert len(google_calls) == 1  # 30-day span
    # First meta window starts at the platform start; last ends at end_date.
    assert meta_calls[0][1] == "2026-01-01"
    assert meta_calls[-1][2] == "2026-03-01"

    r = results[0]
    assert r.status == "backfilled"
    assert r.accounts == 2
    assert r.windows_ok == 3
    assert r.windows_failed == 0
    assert r.rows == 15  # 3 windows x 1 connection x 5 rows each


def test_skips_workspace_with_no_active_accounts(monkeypatch):
    workspaces = [FakeWorkspace("w1")]
    connections_by_ws = {"w1": [FakeConnection("meta_ads", "a", status="revoked")]}
    _patch_repo(monkeypatch, workspaces=workspaces, connections_by_ws=connections_by_ws)

    def fake_run(**kwargs):  # pragma: no cover - must not run
        raise AssertionError("no active accounts -> should not sync")

    results = backfill_all(
        session=object(),
        destination=object(),
        meta_connector_factory=lambda t: None,
        google_connector_factory=lambda t: None,
        end_date="2026-03-01",
        platform_starts={"meta_ads": "2026-01-01"},
        run_sync=fake_run,
    )
    assert results[0].status == "skipped"


def test_one_failing_window_is_isolated_and_progress_persists(monkeypatch):
    workspaces = [FakeWorkspace("w1")]
    connections_by_ws = {"w1": [FakeConnection("meta_ads", "act_1")]}
    _patch_repo(monkeypatch, workspaces=workspaces, connections_by_ws=connections_by_ws)

    def fake_run(**kwargs):
        # Fail only the first (oldest) window; later windows must still run.
        if kwargs["start_date"] == "2026-01-01":
            raise RuntimeError("Service temporarily unavailable")
        return _ok(kwargs["connections"])

    results = backfill_all(
        session=object(),
        destination=object(),
        meta_connector_factory=lambda t: None,
        google_connector_factory=lambda t: None,
        end_date="2026-03-01",
        platform_starts={"meta_ads": "2026-01-01"},  # 60-day span -> 2 windows
        window_days=30,
        run_sync=fake_run,
    )

    r = results[0]
    assert r.status == "backfilled"  # at least one window succeeded
    assert r.windows_ok == 1
    assert r.windows_failed == 1
    assert r.detail == "RuntimeError"
