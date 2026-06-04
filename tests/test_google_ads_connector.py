"""Tests for Google Ads connector account discovery."""

from __future__ import annotations

from types import SimpleNamespace

from src.connectors.google_ads import GoogleAdsConnector


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
