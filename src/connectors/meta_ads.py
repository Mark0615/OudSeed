"""Meta Ads Insights API connector."""

import json
import re
from typing import Any

import requests

from src.connectors.base import BaseAdsConnector


DEFAULT_META_INSIGHTS_FIELDS = [
    "date_start",
    "date_stop",
    "account_id",
    "account_name",
    "campaign_id",
    "campaign_name",
    "adset_id",
    "adset_name",
    "ad_id",
    "ad_name",
    "impressions",
    "clicks",
    "inline_link_clicks",
    "spend",
    "actions",
    "action_values",
    "cost_per_action_type",
    "outbound_clicks",
]


class MetaAdsConnector(BaseAdsConnector):
    """Fetch ad-level daily data from Meta Ads Insights API."""

    platform_name = "meta_ads"

    def __init__(
        self,
        access_token: str,
        api_version: str = "v24.0",
        fields: list[str] | None = None,
        timeout_seconds: int = 60,
        session: requests.Session | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("Meta access_token is required.")

        self.access_token = access_token
        self.api_version = api_version
        self.fields = fields or DEFAULT_META_INSIGHTS_FIELDS
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.base_url = f"https://graph.facebook.com/{api_version}"

    def fetch_daily_report(
        self,
        account_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """Fetch Meta Ads daily Insights rows for an account and date range."""
        url = self._insights_url(account_id)
        params: dict[str, Any] = {
            "access_token": self.access_token,
            "fields": ",".join(self.fields),
            "level": "ad",
            "time_increment": 1,
            "time_range": json.dumps({"since": start_date, "until": end_date}),
            "limit": 500,
        }

        rows: list[dict] = []
        while url:
            payload = self._get_json(url, params=params)
            data = payload.get("data", [])
            if not isinstance(data, list):
                raise RuntimeError("Meta Ads API response field 'data' must be a list.")

            rows.extend(data)
            url = payload.get("paging", {}).get("next")
            params = None

        return rows

    def _insights_url(self, account_id: str) -> str:
        """Build the insights endpoint URL for an ad account."""
        if not account_id.startswith("act_"):
            raise ValueError("Meta ad account ID must start with 'act_'.")
        return f"{self.base_url}/{account_id}/insights"

    def _get_json(self, url: str, params: dict[str, Any] | None) -> dict:
        """Execute a GET request and return parsed JSON with readable errors."""
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                "Meta Ads API request failed: "
                f"{exc.__class__.__name__}: {_redact_token(str(exc))}"
            ) from exc

        if response.status_code >= 400:
            raise RuntimeError(
                "Meta Ads API request failed "
                f"with status {response.status_code}: {_redact_token(response.text)}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Meta Ads API returned invalid JSON.") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("Meta Ads API response must be a JSON object.")
        if "error" in payload:
            raise RuntimeError(f"Meta Ads API returned error: {payload['error']}")

        return payload


def _redact_token(value: str) -> str:
    """Redact common token shapes from error strings before logging."""
    return re.sub(r"(access_token=)[^&\s)]+", r"\1REDACTED", value)
