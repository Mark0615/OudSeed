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
    "objective",
    "impressions",
    "reach",
    "frequency",
    "clicks",
    "unique_clicks",
    "inline_link_clicks",
    "spend",
    "cpc",
    "cpm",
    "ctr",
    "outbound_clicks",
    "outbound_clicks_ctr",
    # Nested arrays (action_type -> value). The wide BigQuery view flattens these
    # into named columns (purchases, adds_to_cart, leads, ...).
    "actions",
    "action_values",
    "cost_per_action_type",
    "unique_actions",
    "cost_per_unique_action_type",
    # ROAS arrays (action_type -> value).
    "purchase_roas",
    "website_purchase_roas",
    # Video engagement (arrays keyed by action_type).
    "video_play_actions",
    "video_thruplay_watched_actions",
    "video_p25_watched_actions",
    "video_p50_watched_actions",
    "video_p75_watched_actions",
    "video_p100_watched_actions",
    "video_avg_time_watched_actions",
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

    def fetch_ad_accounts(self) -> list[dict[str, Any]]:
        """Fetch ad accounts accessible by the current token."""
        url = f"{self.base_url}/me/adaccounts"
        params: dict[str, Any] | None = {
            "access_token": self.access_token,
            "fields": "id,name,account_id,currency,timezone_name,account_status",
            "limit": 500,
        }

        accounts: list[dict[str, Any]] = []
        while url:
            payload = self._get_json(url, params=params)
            data = payload.get("data", [])
            if not isinstance(data, list):
                raise RuntimeError("Meta Ads API response field 'data' must be a list.")

            for account in data:
                if not isinstance(account, dict):
                    continue
                account_id = str(account.get("id") or "")
                if account_id and not account_id.startswith("act_"):
                    account_id = f"act_{account_id}"
                accounts.append(
                    {
                        "id": account_id,
                        "name": str(account.get("name") or account_id or "Unnamed Meta Ads Account"),
                        "currency": account.get("currency"),
                        "timezone": account.get("timezone_name"),
                        "status": _meta_account_status_label(account.get("account_status")),
                    }
                )

            url = payload.get("paging", {}).get("next")
            params = None

        return accounts

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


def _meta_account_status_label(status: object) -> str:
    """Return a readable non-sensitive account status label."""
    labels = {
        1: "Active",
        2: "Disabled",
        3: "Unsettled",
        7: "Pending review",
        9: "In grace period",
        100: "Pending closure",
        101: "Closed",
        201: "Any active",
        202: "Any closed",
    }
    try:
        status_id = int(status)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "Unknown"
    return labels.get(status_id, f"Status {status_id}")
