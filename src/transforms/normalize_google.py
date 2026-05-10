"""Normalize Google Ads rows into the unified ads schema."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def normalize_google_ads_rows(raw_rows: list[dict], context: dict) -> list[dict]:
    """Normalize Google Ads ad-level rows into unified_ads_daily rows."""
    workspace_id = _required_context(context, "workspace_id")
    client_id = _required_context(context, "client_id")
    account_id = _required_context(context, "account_id")
    account_name = context.get("account_name")
    now = datetime.now(timezone.utc).isoformat()
    normalized_rows: list[dict] = []

    for raw_row in raw_rows:
        if raw_row.get("report_level") != "ad":
            continue

        spend = _to_float(raw_row.get("spend"))
        conversions = _to_float(raw_row.get("conversions"))
        conversion_value = _to_float(raw_row.get("conversion_value"))
        impressions = _to_int(raw_row.get("impressions"))
        clicks = _to_int(raw_row.get("clicks"))

        normalized_rows.append(
            {
                "date": raw_row.get("date"),
                "workspace_id": workspace_id,
                "client_id": client_id,
                "platform": "google_ads",
                "account_id": account_id,
                "account_name": raw_row.get("account_name") or account_name,
                "campaign_id": raw_row.get("campaign_id"),
                "campaign_name": raw_row.get("campaign_name"),
                "ad_group_id": raw_row.get("ad_group_id"),
                "ad_group_name": raw_row.get("ad_group_name"),
                "ad_id": raw_row.get("ad_id"),
                "ad_name": raw_row.get("ad_name"),
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "conversions": conversions,
                "conversion_value": conversion_value,
                "add_to_cart": 0.0,
                "purchase": conversions,
                "purchase_value": conversion_value,
                "cost_per_add_to_cart": None,
                "cost_per_purchase": _safe_divide(spend, conversions),
                "outbound_clicks": clicks,
                "page_engagement": 0.0,
                "post_engagement": 0.0,
                "post_reactions": 0.0,
                "post_comments": 0.0,
                "post_saves": 0.0,
                "post_shares": 0.0,
                "ctr": _to_optional_float(raw_row.get("ctr"))
                or _safe_divide(clicks, impressions),
                "cpc": _to_optional_float(raw_row.get("cpc"))
                or _safe_divide(spend, clicks),
                "cpm": _to_optional_float(raw_row.get("cpm"))
                or _safe_divide(spend * 1000, impressions),
                "cpa": _to_optional_float(raw_row.get("cpa"))
                or _safe_divide(spend, conversions),
                "roas": _safe_divide(conversion_value, spend),
                "currency": raw_row.get("currency"),
                "source_updated_at": None,
                "created_at": now,
                "updated_at": now,
            }
        )

    return normalized_rows


def _required_context(context: dict, key: str) -> str:
    value = context.get(key)
    if not value:
        raise ValueError(f"Missing required context field: {key}")
    return str(value)


def _to_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    return int(value)


def _to_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _to_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _safe_divide(numerator: float | int, denominator: float | int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator
