"""Tests for the on-demand first-sync orchestrator (offline, fake connectors)."""

from __future__ import annotations

from src.storage.crypto import encrypt_secret, generate_key
from src.storage.models import PlatformConnection
from src.web.first_sync import run_first_sync

KEY = generate_key()


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
    """Records replace_date_range calls and returns the row count written."""

    def __init__(self):
        self.calls = []

    def replace_date_range(self, *, table_name, rows, start_date, end_date, filters):
        self.calls.append(
            {"table_name": table_name, "rows": rows, "filters": filters}
        )
        return len(rows)


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
    )


def test_first_sync_writes_unified_rows_with_web_tenant_ids():
    dest = FakeDestination()
    result = _run([_conn("meta_ads", "act_111")], dest)

    assert result.attempted == 1
    assert len(result.succeeded) == 1
    assert not result.has_failures
    assert result.total_rows == 1

    # Wrote to unified_ads_daily, scoped to the web tenant ids.
    call = dest.calls[0]
    assert call["table_name"] == "unified_ads_daily"
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
    # The good account was still written.
    assert len(dest.calls) == 1


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
