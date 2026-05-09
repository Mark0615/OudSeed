"""Tests for Meta Ads connector."""

from unittest.mock import Mock

import pytest
import requests

from src.connectors.meta_ads import DEFAULT_META_INSIGHTS_FIELDS, MetaAdsConnector


def make_response(status_code: int, payload: object, text: str = "") -> Mock:
    """Create a mock requests response."""
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.json.return_value = payload
    return response


def test_meta_connector_requires_access_token() -> None:
    """Access token is required."""
    with pytest.raises(ValueError, match="access_token is required"):
        MetaAdsConnector(access_token="")


def test_fetch_daily_report_calls_insights_endpoint() -> None:
    """Connector calls the ad account Insights endpoint with default fields."""
    session = Mock()
    session.get.return_value = make_response(
        200,
        {
            "data": [
                {
                    "date_start": "2026-05-03",
                    "campaign_id": "campaign_1",
                }
            ]
        },
    )
    connector = MetaAdsConnector(access_token="token", session=session)

    rows = connector.fetch_daily_report(
        account_id="act_000000000000000",
        start_date="2026-04-26",
        end_date="2026-05-03",
    )

    assert rows == [{"date_start": "2026-05-03", "campaign_id": "campaign_1"}]
    url = session.get.call_args.args[0]
    params = session.get.call_args.kwargs["params"]
    assert url == "https://graph.facebook.com/v24.0/act_000000000000000/insights"
    assert params["fields"] == ",".join(DEFAULT_META_INSIGHTS_FIELDS)
    assert "inline_link_clicks" in params["fields"]
    assert "cost_per_action_type" in params["fields"]
    assert "outbound_clicks" in params["fields"]
    assert "currency" not in params["fields"]
    assert params["level"] == "ad"
    assert params["time_increment"] == 1
    assert params["time_range"] == '{"since": "2026-04-26", "until": "2026-05-03"}'


def test_fetch_daily_report_supports_pagination() -> None:
    """Connector follows paging.next until exhausted."""
    session = Mock()
    session.get.side_effect = [
        make_response(
            200,
            {
                "data": [{"ad_id": "ad_1"}],
                "paging": {"next": "https://graph.facebook.com/next-page"},
            },
        ),
        make_response(200, {"data": [{"ad_id": "ad_2"}]}),
    ]
    connector = MetaAdsConnector(access_token="token", session=session)

    rows = connector.fetch_daily_report(
        account_id="act_000000000000000",
        start_date="2026-04-26",
        end_date="2026-05-03",
    )

    assert rows == [{"ad_id": "ad_1"}, {"ad_id": "ad_2"}]
    assert session.get.call_count == 2
    assert session.get.call_args_list[1].args[0] == "https://graph.facebook.com/next-page"
    assert session.get.call_args_list[1].kwargs["params"] is None


def test_fetch_daily_report_rejects_invalid_account_id() -> None:
    """Meta account IDs must use act_ prefix."""
    connector = MetaAdsConnector(access_token="token", session=Mock())

    with pytest.raises(ValueError, match="must start with 'act_'"):
        connector.fetch_daily_report("123", "2026-04-26", "2026-05-03")


def test_fetch_daily_report_raises_for_http_error() -> None:
    """HTTP errors include status and response body."""
    session = Mock()
    session.get.return_value = make_response(400, {}, text="bad request")
    connector = MetaAdsConnector(access_token="token", session=session)

    with pytest.raises(RuntimeError, match="status 400: bad request"):
        connector.fetch_daily_report("act_000000000000000", "2026-04-26", "2026-05-03")


def test_fetch_daily_report_raises_for_request_exception() -> None:
    """Network/request exceptions are wrapped with context."""
    session = Mock()
    session.get.side_effect = requests.Timeout("slow")
    connector = MetaAdsConnector(access_token="token", session=session)

    with pytest.raises(RuntimeError, match="Meta Ads API request failed"):
        connector.fetch_daily_report("act_000000000000000", "2026-04-26", "2026-05-03")


def test_fetch_daily_report_raises_for_api_error_payload() -> None:
    """Meta error payloads are surfaced."""
    session = Mock()
    session.get.return_value = make_response(200, {"error": {"message": "bad token"}})
    connector = MetaAdsConnector(access_token="token", session=session)

    with pytest.raises(RuntimeError, match="bad token"):
        connector.fetch_daily_report("act_000000000000000", "2026-04-26", "2026-05-03")


def test_fetch_daily_report_raises_when_data_is_not_list() -> None:
    """Unexpected response shapes fail loudly."""
    session = Mock()
    session.get.return_value = make_response(200, {"data": {"bad": "shape"}})
    connector = MetaAdsConnector(access_token="token", session=session)

    with pytest.raises(RuntimeError, match="'data' must be a list"):
        connector.fetch_daily_report("act_000000000000000", "2026-04-26", "2026-05-03")
