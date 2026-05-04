"""Tests for the Meta sync flow."""

from src.main import RAW_META_TABLE, SYNC_LOGS_TABLE, UNIFIED_TABLE, run_meta_sync


class FakeConnector:
    """Fake Meta connector for sync tests."""

    def __init__(self, rows: list[dict] | None = None, error: Exception | None = None) -> None:
        self.rows = rows or []
        self.error = error
        self.calls: list[dict] = []

    def fetch_daily_report(self, account_id: str, start_date: str, end_date: str) -> list[dict]:
        """Return fake rows or raise a fake error."""
        self.calls.append(
            {
                "account_id": account_id,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        if self.error:
            raise self.error
        return self.rows


class FakeDestination:
    """Fake BigQuery destination for sync tests."""

    def __init__(self) -> None:
        self.replacements: list[dict] = []
        self.inserts: list[dict] = []

    def replace_date_range(
        self,
        table_name: str,
        rows: list[dict],
        start_date: str,
        end_date: str,
        filters: dict,
    ) -> int:
        """Record replacement calls."""
        self.replacements.append(
            {
                "table_name": table_name,
                "rows": rows,
                "start_date": start_date,
                "end_date": end_date,
                "filters": filters,
            }
        )
        return len(rows)

    def insert_rows(self, table_name: str, rows: list[dict]) -> int:
        """Record insert calls."""
        self.inserts.append({"table_name": table_name, "rows": rows})
        return len(rows)


def sample_config() -> dict:
    """Return a minimal enabled Meta config."""
    return {
        "workspace_id": "mark_internal",
        "defaults": {
            "timezone": "Asia/Taipei",
            "sync_days_back": 7,
            "attribution_setting": "platform_default",
            "timezone_setting": "platform_account_default",
            "conversion_action_type": "purchase",
        },
        "clients": [
            {
                "client_id": "demo_client_001",
                "enabled": True,
                "platforms": {
                    "meta_ads": {
                        "enabled": True,
                        "accounts": [
                            {
                                "ad_account_id": "act_000000000000000",
                                "account_name": "Demo Account",
                                "report_level": "ad",
                            }
                        ],
                    }
                },
                "destinations": {"bigquery": {"enabled": True}},
            }
        ],
    }


def sample_raw_rows() -> list[dict]:
    """Return one fake Meta raw row."""
    return [
        {
            "date_start": "2026-05-03",
            "account_id": "1234567890",
            "account_name": "Demo Account",
            "campaign_id": "campaign_001",
            "campaign_name": "Campaign",
            "adset_id": "adset_001",
            "adset_name": "Ad Set",
            "ad_id": "ad_001",
            "ad_name": "Ad",
            "impressions": "100",
            "clicks": "10",
            "inline_link_clicks": "8",
            "spend": "50",
            "actions": [{"action_type": "purchase", "value": "2"}],
            "action_values": [{"action_type": "purchase", "value": "200"}],
        }
    ]


def test_run_meta_sync_writes_raw_unified_and_success_log() -> None:
    """Successful sync writes raw rows, unified rows, and sync log."""
    connector = FakeConnector(rows=sample_raw_rows())
    destination = FakeDestination()

    run_meta_sync(sample_config(), connector, destination)

    assert connector.calls[0]["account_id"] == "act_000000000000000"
    assert [call["table_name"] for call in destination.replacements] == [
        RAW_META_TABLE,
        UNIFIED_TABLE,
    ]
    raw_replacement = destination.replacements[0]
    assert raw_replacement["filters"]["platform"] == "meta_ads"
    assert raw_replacement["rows"][0]["raw_payload"]
    assert isinstance(raw_replacement["rows"][0]["raw_payload"], str)
    unified_replacement = destination.replacements[1]
    assert unified_replacement["rows"][0]["platform"] == "meta_ads"
    assert unified_replacement["rows"][0]["conversions"] == 2.0

    assert destination.inserts[0]["table_name"] == SYNC_LOGS_TABLE
    sync_log = destination.inserts[0]["rows"][0]
    assert sync_log["status"] == "success"
    assert sync_log["rows_fetched"] == 1
    assert sync_log["rows_inserted"] == 1


def test_run_meta_sync_continues_to_sync_log_on_failure() -> None:
    """Failed account writes a failure sync log."""
    connector = FakeConnector(error=RuntimeError("bad token"))
    destination = FakeDestination()

    run_meta_sync(sample_config(), connector, destination)

    assert destination.replacements == []
    sync_log = destination.inserts[0]["rows"][0]
    assert sync_log["status"] == "failed"
    assert sync_log["rows_fetched"] == 0
    assert sync_log["rows_inserted"] == 0
    assert sync_log["error_message"] == "bad token"
