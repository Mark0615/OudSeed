"""Normalize Meta Ads rows into the unified ads schema."""

from datetime import datetime, timezone
from typing import Any


ACTION_ALIASES = {
    "add_to_cart": ("add_to_cart", "omni_add_to_cart", "onsite_conversion.add_to_cart"),
    "purchase": ("purchase", "omni_purchase", "onsite_conversion.purchase"),
    "page_engagement": ("page_engagement",),
    "post_engagement": ("post_engagement",),
    "post_reaction": ("post_reaction",),
    "comment": ("comment",),
    "post_save": ("onsite_conversion.post_save", "post_save"),
    "post_share": ("post", "share"),
    "outbound_click": ("outbound_click",),
}


def normalize_meta_ads_rows(raw_rows: list[dict], context: dict) -> list[dict]:
    """Normalize Meta Ads Insights rows into unified_ads_daily rows."""
    workspace_id = _required_context(context, "workspace_id")
    client_id = _required_context(context, "client_id")
    account_id = _required_context(context, "account_id")
    account_name = context.get("account_name")
    conversion_action_type = context.get("conversion_action_type", "purchase")

    now = datetime.now(timezone.utc).isoformat()
    normalized_rows: list[dict] = []

    for raw_row in raw_rows:
        impressions = _to_int(raw_row.get("impressions"))
        clicks = _to_int(raw_row.get("inline_link_clicks") or raw_row.get("clicks"))
        spend = _to_float(raw_row.get("spend"))
        conversions = _extract_action_value(
            raw_row.get("actions"),
            conversion_action_type,
        )
        conversion_value = _extract_action_value(
            raw_row.get("action_values"),
            conversion_action_type,
        )
        add_to_cart = _extract_first_action_value(
            raw_row.get("actions"),
            ACTION_ALIASES["add_to_cart"],
        )
        purchase = _extract_first_action_value(
            raw_row.get("actions"),
            ACTION_ALIASES["purchase"],
        )
        purchase_value = _extract_first_action_value(
            raw_row.get("action_values"),
            ACTION_ALIASES["purchase"],
        )
        cost_per_add_to_cart = _extract_first_action_value(
            raw_row.get("cost_per_action_type"),
            ACTION_ALIASES["add_to_cart"],
        )
        cost_per_purchase = _extract_first_action_value(
            raw_row.get("cost_per_action_type"),
            ACTION_ALIASES["purchase"],
        )
        outbound_clicks = _to_int(
            _extract_first_action_value(
                raw_row.get("outbound_clicks"),
                ACTION_ALIASES["outbound_click"],
            )
        )
        page_engagement = _extract_first_action_value(
            raw_row.get("actions"),
            ACTION_ALIASES["page_engagement"],
        )
        post_engagement = _extract_first_action_value(
            raw_row.get("actions"),
            ACTION_ALIASES["post_engagement"],
        )
        post_reactions = _extract_first_action_value(
            raw_row.get("actions"),
            ACTION_ALIASES["post_reaction"],
        )
        post_comments = _extract_first_action_value(
            raw_row.get("actions"),
            ACTION_ALIASES["comment"],
        )
        post_saves = _extract_first_action_value(
            raw_row.get("actions"),
            ACTION_ALIASES["post_save"],
        )
        post_shares = _extract_first_action_value(
            raw_row.get("actions"),
            ACTION_ALIASES["post_share"],
        )

        normalized_rows.append(
            {
                "date": raw_row.get("date_start"),
                "workspace_id": workspace_id,
                "client_id": client_id,
                "platform": "meta_ads",
                "account_id": account_id,
                "account_name": raw_row.get("account_name") or account_name,
                "campaign_id": raw_row.get("campaign_id"),
                "campaign_name": raw_row.get("campaign_name"),
                "ad_group_id": raw_row.get("adset_id"),
                "ad_group_name": raw_row.get("adset_name"),
                "ad_id": raw_row.get("ad_id"),
                "ad_name": raw_row.get("ad_name"),
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "conversions": conversions,
                "conversion_value": conversion_value,
                "add_to_cart": add_to_cart,
                "purchase": purchase,
                "purchase_value": purchase_value,
                "cost_per_add_to_cart": cost_per_add_to_cart
                or _safe_divide(spend, add_to_cart),
                "cost_per_purchase": cost_per_purchase or _safe_divide(spend, purchase),
                "outbound_clicks": outbound_clicks,
                "page_engagement": page_engagement,
                "post_engagement": post_engagement,
                "post_reactions": post_reactions,
                "post_comments": post_comments,
                "post_saves": post_saves,
                "post_shares": post_shares,
                "ctr": _safe_divide(clicks, impressions),
                "cpc": _safe_divide(spend, clicks),
                "cpm": _safe_divide(spend * 1000, impressions),
                "cpa": _safe_divide(spend, conversions),
                "roas": _safe_divide(conversion_value, spend),
                "currency": raw_row.get("currency"),
                "source_updated_at": None,
                "created_at": now,
                "updated_at": now,
            }
        )

    return normalized_rows


def _required_context(context: dict, key: str) -> str:
    """Return a required non-empty context value."""
    value = context.get(key)
    if not value:
        raise ValueError(f"Missing required context field: {key}")
    return str(value)


def _to_int(value: Any) -> int:
    """Convert API numeric values to int, treating missing values as zero."""
    if value in (None, ""):
        return 0
    return int(value)


def _to_float(value: Any) -> float:
    """Convert API numeric values to float, treating missing values as zero."""
    if value in (None, ""):
        return 0.0
    return float(value)


def _extract_action_value(actions: Any, action_type: str) -> float:
    """Extract a Meta action value by action_type from an actions list."""
    if not isinstance(actions, list):
        return 0.0

    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("action_type") == action_type:
            return _to_float(action.get("value"))

    return 0.0


def _extract_first_action_value(actions: Any, action_types: tuple[str, ...]) -> float:
    """Extract the first matching Meta action value from a list."""
    if not isinstance(actions, list):
        return 0.0

    for action_type in action_types:
        value = _extract_action_value(actions, action_type)
        if value:
            return value

    return 0.0


def _safe_divide(numerator: float | int, denominator: float | int) -> float | None:
    """Divide values, returning None when denominator is zero."""
    if denominator == 0:
        return None
    return numerator / denominator
