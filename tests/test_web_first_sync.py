"""Tests for the on-demand first-sync orchestrator (offline, fake connectors)."""

from __future__ import annotations

import pytest

from src.storage.crypto import encrypt_secret, generate_key
from src.storage.models import PlatformConnection
from src.web.first_sync import (
    _date_chunks,
    _fetch_chunked,
    _fetch_with_retry,
    run_first_sync,
)

KEY = generate_key()
_NO_SLEEP = lambda *_: None  # noqa: E731 - tiny test stub


def _conn(platform: str, account_id: str, token: str = "tok") -> PlatformConnection:
    return PlatformConnection(
        workspace_id="w1",
        platform=platform,
        external_account_id=account_id,
        account_name=f"{platform} {account_id}",
        status="active",
        encrypted_token=encrypt_secret(token, key=KEY),
    )


class FakeDestination:
    """Records replace_date_range/execute_sql calls and returns the row count."""

    def __init__(self):
        self.calls = []
        self.ddl = []

    def replace_date_range(self, *, table_name, rows, start_date, end_date, filters):
        self.calls.append(
            {"table_name": table_name, "rows": rows, "filters": filters}
        )
        return len(rows)

    def execute_sql(self, sql):
        self.ddl.append(sql)

    def qualified_table(self, table_name):
        return f"proj.ds.{table_name}"

    def calls_for(self, table_name):
        return [c for c in self.calls if c["table_name"] == table_name]


class FakeMetaConnector:
    def __init__(self, token):
        self.token = token

    def fetch_daily_report(self, *, account_id, start_date, end_date):
        return [
            {
                "date_start": start_date,
                "campaign_name": "Brand A",
                "impressions": "1000",
                "inline_link_clicks": "50",
                "spend": "120.5",
            }
        ]


class FakeGoogleConnector:
    def __init__(self, token):
        self.token = token

    def fetch_daily_report(self, *, customer_id, start_date, end_date):
        return [
            {
                "date": start_date,
                "campaign_name": "Search B",
                "impressions": "500",
                "clicks": "30",
                "cost": "80.0",
            }
        ]


class BoomConnector:
    def __init__(self, token):
        pass

    def fetch_daily_report(self, **kwargs):
        raise RuntimeError("ad API exploded")


def _run(connections, dest, *, meta=FakeMetaConnector, google=FakeGoogleConnector):
    return run_first_sync(
        connections=connections,
        destination=dest,
        workspace_id="w1",
        client_id="default",
        start_date="2026-05-10",
        end_date="2026-06-08",
        meta_connector_factory=meta,
        google_connector_factory=google,
        token_key=KEY,
        # Single chunk + no real backoff so these behavior tests stay deterministic.
        chunk_days=60,
        sleep=_NO_SLEEP,
    )


def test_first_sync_writes_unified_rows_with_web_tenant_ids():
    dest = FakeDestination()
    result = _run([_conn("meta_ads", "act_111")], dest)

    assert result.attempted == 1
    assert len(result.succeeded) == 1
    assert not result.has_failures
    assert result.total_rows == 1

    # Wrote to unified_ads_daily, scoped to the web tenant ids.
    call = dest.calls_for("unified_ads_daily")[0]
    assert call["filters"] == {
        "workspace_id": "w1",
        "client_id": "default",
        "platform": "meta_ads",
        "account_id": "act_111",
    }
    # The normalized row carries the web ids (not config ids).
    row = call["rows"][0]
    assert row["workspace_id"] == "w1"
    assert row["client_id"] == "default"
    assert row["account_id"] == "act_111"

    # Also preserved the full payload in raw_meta_ads_daily (for the wide view),
    # after ensuring the raw table exists.
    raw_call = dest.calls_for("raw_meta_ads_daily")[0]
    assert raw_call["rows"][0]["raw_payload"]["campaign_name"] == "Brand A"
    assert any("CREATE TABLE IF NOT EXISTS" in d for d in dest.ddl)


def test_first_sync_handles_both_platforms():
    dest = FakeDestination()
    result = _run([_conn("meta_ads", "act_1"), _conn("google_ads", "9990001112")], dest)
    assert result.attempted == 2
    assert len(result.succeeded) == 2
    platforms = {c["filters"]["platform"] for c in dest.calls}
    assert platforms == {"meta_ads", "google_ads"}


def test_first_sync_isolates_per_account_failures():
    dest = FakeDestination()

    # The second account's connector explodes; the first must still be written.
    def meta_factory(token):
        meta_factory.calls += 1
        return BoomConnector(token) if meta_factory.calls == 2 else FakeMetaConnector(token)

    meta_factory.calls = 0
    result = _run(
        [_conn("meta_ads", "ok_1"), _conn("meta_ads", "bad_2")], dest, meta=meta_factory
    )

    assert result.attempted == 2
    assert len(result.succeeded) == 1
    assert len(result.failed) == 1
    assert result.failed[0].account_id == "bad_2"
    assert "exploded" in (result.failed[0].error or "")
    # The good account was still written (raw + unified), the bad one not at all.
    assert len(dest.calls_for("unified_ads_daily")) == 1
    assert len(dest.calls_for("raw_meta_ads_daily")) == 1


def test_first_sync_fails_account_without_token():
    dest = FakeDestination()
    conn = PlatformConnection(
        workspace_id="w1",
        platform="meta_ads",
        external_account_id="act_x",
        status="active",
        encrypted_token=None,
    )
    result = _run([conn], dest)
    assert len(result.failed) == 1
    assert "token" in (result.failed[0].error or "").lower()
    assert dest.calls == []


def test_date_chunks_splits_inclusive_range():
    chunks = _date_chunks("2026-05-10", "2026-06-08", 7)
    # 30 inclusive days / 7 -> 5 contiguous, non-overlapping windows.
    assert len(chunks) == 5
    assert chunks[0] == ("2026-05-10", "2026-05-16")
    assert chunks[1][0] == "2026-05-17"
    assert chunks[-1] == ("2026-06-07", "2026-06-08")


def test_fetch_chunked_retries_transient_then_concatenates():
    calls: list[tuple[str, str]] = []

    def fetch(start_date, end_date):
        calls.append((start_date, end_date))
        # The second chunk fails transiently on its first attempt, then succeeds.
        if start_date == "2026-05-17" and calls.count((start_date, end_date)) == 1:
            raise RuntimeError(
                "Meta Ads API request failed with status 400: Service temporarily unavailable"
            )
        return [{"window": start_date}]

    rows = _fetch_chunked(
        fetch, "2026-05-10", "2026-05-23", chunk_days=7, max_attempts=3, sleep=_NO_SLEEP
    )
    # Two chunks; the second was retried once -> two rows total.
    assert [r["window"] for r in rows] == ["2026-05-10", "2026-05-17"]
    assert calls.count(("2026-05-17", "2026-05-23")) == 2


def test_fetch_with_retry_fails_fast_on_permanent_error():
    calls: list[tuple[str, str]] = []

    def fetch(start_date, end_date):
        calls.append((start_date, end_date))
        raise RuntimeError("Meta Ads API request failed with status 403: PERMISSION_DENIED")

    with pytest.raises(RuntimeError):
        _fetch_with_retry(
            fetch, "2026-05-10", "2026-05-16", max_attempts=3, sleep=_NO_SLEEP
        )
    # Permanent errors are not retried.
    assert len(calls) == 1


def test_first_sync_chunks_a_large_window():
    dest = FakeDestination()
    result = run_first_sync(
        connections=[_conn("meta_ads", "act_111")],
        destination=dest,
        workspace_id="w1",
        client_id="default",
        start_date="2026-05-10",
        end_date="2026-06-08",
        meta_connector_factory=FakeMetaConnector,
        google_connector_factory=FakeGoogleConnector,
        token_key=KEY,
        chunk_days=7,
        sleep=_NO_SLEEP,
    )
    # 30-day window / 7 -> 5 chunks; the fake returns one row per chunk, all
    # written in a single unified (and a single raw) replace_date_range call.
    assert result.total_rows == 5
    unified = dest.calls_for("unified_ads_daily")
    assert len(unified) == 1
    assert len(unified[0]["rows"]) == 5
    assert len(dest.calls_for("raw_meta_ads_daily")[0]["rows"]) == 5
