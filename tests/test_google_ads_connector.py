"""Tests for Google Ads connector account discovery."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.connectors.google_ads import GoogleAdsConnector, _flatten_google_ads_row


class FakeCustomerService:
    def __init__(self, resource_names: list[str]) -> None:
        self.resource_names = resource_names

    def list_accessible_customers(self) -> SimpleNamespace:
        return SimpleNamespace(resource_names=self.resource_names)


class FakeGoogleAdsService:
    def __init__(self, rows_by_customer: dict[str, list[object]]) -> None:
        self.rows_by_customer = rows_by_customer
        self.calls: list[dict[str, str]] = []

    def search_stream(self, *, customer_id: str, query: str) -> list[SimpleNamespace]:
        self.calls.append({"customer_id": customer_id, "query": query})
        return [SimpleNamespace(results=self.rows_by_customer.get(customer_id, []))]


def make_connector(
    *,
    resource_names: list[str],
    rows_by_customer: dict[str, list[object]],
) -> GoogleAdsConnector:
    connector = GoogleAdsConnector.__new__(GoogleAdsConnector)
    connector.customer_service = FakeCustomerService(resource_names)
    connector.google_ads_service = FakeGoogleAdsService(rows_by_customer)
    return connector


def test_fetch_customer_accounts_lists_accessible_google_customers() -> None:
    connector = make_connector(
        resource_names=["customers/123-456-7890"],
        rows_by_customer={},
    )

    accounts = connector.fetch_customer_accounts()

    assert accounts == [
        {
            "id": "1234567890",
            "name": "Google Ads Customer 1",
            "currency": None,
            "timezone": None,
            "status": "Ready",
        }
    ]
    assert connector.google_ads_service.calls == []


def test_fetch_customer_accounts_can_include_metadata_when_requested() -> None:
    connector = make_connector(
        resource_names=["customers/123-456-7890"],
        rows_by_customer={
            "1234567890": [
                SimpleNamespace(
                    customer=SimpleNamespace(
                        id="1234567890",
                        descriptive_name="Demo Google Ads",
                        currency_code="TWD",
                        time_zone="Asia/Taipei",
                    )
                )
            ]
        },
    )

    accounts = connector.fetch_customer_accounts(include_metadata=True)

    assert accounts == [
        {
            "id": "1234567890",
            "name": "Demo Google Ads",
            "currency": "TWD",
            "timezone": "Asia/Taipei",
            "status": "Ready",
        }
    ]
    assert connector.google_ads_service.calls[0]["customer_id"] == "1234567890"
    assert "FROM customer" in connector.google_ads_service.calls[0]["query"]


def test_fetch_customer_accounts_uses_safe_fallback_when_metadata_is_unavailable() -> None:
    connector = make_connector(
        resource_names=["customers/2345678901"],
        rows_by_customer={"2345678901": []},
    )

    accounts = connector.fetch_customer_accounts()

    assert accounts == [
        {
            "id": "2345678901",
            "name": "Google Ads Customer 1",
            "currency": None,
            "timezone": None,
            "status": "Ready",
        }
    ]


class RecordingService:
    """Records every GAQL query and returns no rows (so no flattening happens)."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search_stream(self, *, customer_id: str, query: str) -> list[object]:
        self.queries.append(query)
        return []


def _bare_connector() -> GoogleAdsConnector:
    return GoogleAdsConnector.__new__(GoogleAdsConnector)


def test_fetch_daily_report_runs_all_four_report_levels() -> None:
    """A daily fetch queries ad, keyword, search-term, and conversion-action data."""
    connector = _bare_connector()
    connector.google_ads_service = RecordingService()

    rows = connector.fetch_daily_report(
        customer_id="123-456-7890", start_date="2026-06-01", end_date="2026-06-10"
    )

    assert rows == []
    joined = " ".join(connector.google_ads_service.queries)
    assert "FROM ad_group_ad" in joined
    assert "FROM keyword_view" in joined
    assert "FROM search_term_view" in joined
    assert "FROM campaign" in joined
    assert "segments.conversion_action_name" in joined


def test_flatten_conversion_action_row_maps_named_action_and_metrics() -> None:
    """Conversion-action rows flatten to the named action + conversion metrics only."""
    row = SimpleNamespace(
        segments=SimpleNamespace(
            date="2026-06-10",
            conversion_action_name="Purchase (Custom)",
            conversion_action_category=SimpleNamespace(name="PURCHASE"),
        ),
        customer=SimpleNamespace(
            id=1234567890, descriptive_name="Demo Google Ads", currency_code="TWD"
        ),
        campaign=SimpleNamespace(
            id=111,
            name="Search - Brand",
            status=SimpleNamespace(name="ENABLED"),
            advertising_channel_type=SimpleNamespace(name="SEARCH"),
        ),
        metrics=SimpleNamespace(
            conversions=3.0,
            conversions_value=900.0,
            all_conversions=4.0,
            all_conversions_value=1200.0,
        ),
    )

    flattened = _flatten_google_ads_row(row, report_level="conversion_action")

    assert flattened == {
        "date": "2026-06-10",
        "report_level": "conversion_action",
        "customer_id": "1234567890",
        "account_name": "Demo Google Ads",
        "currency": "TWD",
        "campaign_id": "111",
        "campaign_name": "Search - Brand",
        "campaign_status": "ENABLED",
        "campaign_channel_type": "SEARCH",
        "conversion_action_name": "Purchase (Custom)",
        "conversion_action_category": "PURCHASE",
        "conversions": 3.0,
        "conversion_value": 900.0,
        "all_conversions": 4.0,
        "all_conversions_value": 1200.0,
    }
    # No spend/impressions leak into the conversion-action grain.
    assert "spend" not in flattened
    assert "impressions" not in flattened


class _RaisingService:
    def search_stream(self, *, customer_id: str, query: str) -> list[object]:
        raise RuntimeError("account cannot serve this query")


def test_optional_query_failure_does_not_raise() -> None:
    """An optional breakdown that errors returns [] instead of aborting the sync."""
    connector = _bare_connector()
    connector.google_ads_service = _RaisingService()

    assert (
        connector._run_query(
            customer_id="1", query="SELECT 1", report_level="conversion_action", optional=True
        )
        == []
    )


def test_non_optional_query_failure_still_raises() -> None:
    """Core (non-optional) queries still surface failures."""
    connector = _bare_connector()
    connector.google_ads_service = _RaisingService()

    with pytest.raises(RuntimeError):
        connector._run_query(customer_id="1", query="SELECT 1", report_level="ad")
