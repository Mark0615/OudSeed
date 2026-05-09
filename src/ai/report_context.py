"""Build AI-ready report context from reporting marts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from google.cloud import bigquery

from src.destinations.bigquery import BigQueryDestination


ReportType = Literal["weekly", "monthly"]


@dataclass(frozen=True)
class ReportMetricConfig:
    """Field names that differ between weekly and monthly marts."""

    view_name: str
    start_field: str
    end_field: str
    comparison_label: str
    previous_spend_field: str
    previous_clicks_field: str
    previous_conversions_field: str
    previous_add_to_cart_field: str
    previous_purchase_field: str
    spend_delta_field: str
    clicks_delta_field: str
    spend_rate_field: str
    clicks_rate_field: str


REPORT_CONFIGS: dict[ReportType, ReportMetricConfig] = {
    "weekly": ReportMetricConfig(
        view_name="vw_looker_ads_campaign_weekly",
        start_field="week_start_date",
        end_field="week_end_date",
        comparison_label="week_over_week",
        previous_spend_field="previous_week_spend",
        previous_clicks_field="previous_week_link_clicks",
        previous_conversions_field="previous_week_conversions",
        previous_add_to_cart_field="previous_week_add_to_cart",
        previous_purchase_field="previous_week_purchase",
        spend_delta_field="spend_wow",
        clicks_delta_field="link_clicks_wow",
        spend_rate_field="spend_wow_rate",
        clicks_rate_field="link_clicks_wow_rate",
    ),
    "monthly": ReportMetricConfig(
        view_name="vw_looker_ads_campaign_monthly",
        start_field="month_start_date",
        end_field="month_end_date",
        comparison_label="month_over_month",
        previous_spend_field="previous_month_spend",
        previous_clicks_field="previous_month_link_clicks",
        previous_conversions_field="previous_month_conversions",
        previous_add_to_cart_field="previous_month_add_to_cart",
        previous_purchase_field="previous_month_purchase",
        spend_delta_field="spend_mom",
        clicks_delta_field="link_clicks_mom",
        spend_rate_field="spend_mom_rate",
        clicks_rate_field="link_clicks_mom_rate",
    ),
}


def build_report_context(
    destination: BigQueryDestination,
    report_type: ReportType,
    workspace_id: str,
    client_id: str,
    period_start_date: str,
    account_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Return AI-ready summary context for one weekly or monthly period."""
    if limit < 1:
        raise ValueError("limit must be greater than or equal to 1.")

    config = REPORT_CONFIGS[report_type]
    view_id = destination._table_id(config.view_name)
    filters = [
        f"{config.start_field} = @period_start_date",
        "workspace_id = @workspace_id",
        "client_id = @client_id",
    ]
    query_parameters: list[bigquery.ScalarQueryParameter] = [
        bigquery.ScalarQueryParameter("period_start_date", "DATE", period_start_date),
        bigquery.ScalarQueryParameter("workspace_id", "STRING", workspace_id),
        bigquery.ScalarQueryParameter("client_id", "STRING", client_id),
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
    ]

    if account_id:
        filters.append("account_id = @account_id")
        query_parameters.append(
            bigquery.ScalarQueryParameter("account_id", "STRING", account_id)
        )

    query = f"""
    WITH scoped AS (
      SELECT
        {config.start_field} AS period_start_date,
        {config.end_field} AS period_end_date,
        workspace_id,
        client_id,
        platform,
        account_id,
        account_name,
        campaign_id,
        campaign_name,
        impressions,
        link_clicks,
        spend,
        conversions,
        conversion_value,
        add_to_cart,
        purchase,
        purchase_value,
        cost_per_add_to_cart,
        cost_per_purchase,
        outbound_clicks,
        page_engagement,
        post_engagement,
        post_reactions,
        post_comments,
        post_saves,
        post_shares,
        ctr,
        cpc,
        cpm,
        cpa,
        roas,
        {config.previous_spend_field} AS previous_spend,
        {config.previous_clicks_field} AS previous_link_clicks,
        {config.previous_conversions_field} AS previous_conversions,
        {config.previous_add_to_cart_field} AS previous_add_to_cart,
        {config.previous_purchase_field} AS previous_purchase,
        {config.spend_delta_field} AS spend_delta,
        {config.clicks_delta_field} AS link_clicks_delta,
        {config.spend_rate_field} AS spend_delta_rate,
        {config.clicks_rate_field} AS link_clicks_delta_rate
      FROM `{view_id}`
      WHERE {" AND ".join(filters)}
    )
    SELECT
      scoped.*,
      SUM(impressions) OVER() AS total_impressions,
      SUM(link_clicks) OVER() AS total_link_clicks,
      SUM(spend) OVER() AS total_spend,
      SUM(conversions) OVER() AS total_conversions,
      SUM(conversion_value) OVER() AS total_conversion_value,
      SUM(previous_spend) OVER() AS total_previous_spend,
      SUM(previous_link_clicks) OVER() AS total_previous_link_clicks,
      SUM(previous_conversions) OVER() AS total_previous_conversions,
      SUM(previous_add_to_cart) OVER() AS total_previous_add_to_cart,
      SUM(previous_purchase) OVER() AS total_previous_purchase,
      SUM(add_to_cart) OVER() AS total_add_to_cart,
      SUM(purchase) OVER() AS total_purchase,
      SUM(purchase_value) OVER() AS total_purchase_value,
      SUM(outbound_clicks) OVER() AS total_outbound_clicks,
      SUM(page_engagement) OVER() AS total_page_engagement,
      SUM(post_engagement) OVER() AS total_post_engagement,
      SUM(post_reactions) OVER() AS total_post_reactions,
      SUM(post_comments) OVER() AS total_post_comments,
      SUM(post_saves) OVER() AS total_post_saves,
      SUM(post_shares) OVER() AS total_post_shares
    FROM scoped
    ORDER BY spend DESC
    LIMIT @limit
    """
    rows = destination.query_rows(query, query_parameters=query_parameters)
    campaigns = [_normalize_campaign(row) for row in rows]

    return {
        "report_type": report_type,
        "comparison": config.comparison_label,
        "workspace_id": workspace_id,
        "client_id": client_id,
        "account_id": account_id,
        "period_start_date": period_start_date,
        "period_end_date": _first_value(campaigns, "period_end_date"),
        "totals": _extract_totals(rows),
        "campaigns": campaigns,
    }


def _normalize_campaign(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize BigQuery row values into JSON-friendly report fields."""
    return {
        "period_start_date": _format_date(row.get("period_start_date")),
        "period_end_date": _format_date(row.get("period_end_date")),
        "platform": row.get("platform"),
        "account_id": row.get("account_id"),
        "account_name": row.get("account_name"),
        "campaign_id": row.get("campaign_id"),
        "campaign_name": row.get("campaign_name"),
        "impressions": _to_number(row.get("impressions")),
        "link_clicks": _to_number(row.get("link_clicks")),
        "spend": _to_number(row.get("spend")),
        "conversions": _to_number(row.get("conversions")),
        "conversion_value": _to_number(row.get("conversion_value")),
        "add_to_cart": _to_number(row.get("add_to_cart")),
        "purchase": _to_number(row.get("purchase")),
        "purchase_value": _to_number(row.get("purchase_value")),
        "cost_per_add_to_cart": _to_number(row.get("cost_per_add_to_cart")),
        "cost_per_purchase": _to_number(row.get("cost_per_purchase")),
        "outbound_clicks": _to_number(row.get("outbound_clicks")),
        "page_engagement": _to_number(row.get("page_engagement")),
        "post_engagement": _to_number(row.get("post_engagement")),
        "post_reactions": _to_number(row.get("post_reactions")),
        "post_comments": _to_number(row.get("post_comments")),
        "post_saves": _to_number(row.get("post_saves")),
        "post_shares": _to_number(row.get("post_shares")),
        "ctr": _to_number(row.get("ctr")),
        "cpc": _to_number(row.get("cpc")),
        "cpm": _to_number(row.get("cpm")),
        "cpa": _to_number(row.get("cpa")),
        "roas": _to_number(row.get("roas")),
        "previous_spend": _to_number(row.get("previous_spend")),
        "previous_link_clicks": _to_number(row.get("previous_link_clicks")),
        "previous_conversions": _to_number(row.get("previous_conversions")),
        "previous_add_to_cart": _to_number(row.get("previous_add_to_cart")),
        "previous_purchase": _to_number(row.get("previous_purchase")),
        "spend_delta": _to_number(row.get("spend_delta")),
        "link_clicks_delta": _to_number(row.get("link_clicks_delta")),
        "spend_delta_rate": _to_number(row.get("spend_delta_rate")),
        "link_clicks_delta_rate": _to_number(row.get("link_clicks_delta_rate")),
    }


def _extract_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract full-period totals from window fields returned by BigQuery."""
    if not rows:
        return _calculate_rates(
            {
                "impressions": 0,
                "link_clicks": 0,
                "spend": 0,
                "conversions": 0,
                "conversion_value": 0,
                "add_to_cart": 0,
                "purchase": 0,
                "purchase_value": 0,
                "outbound_clicks": 0,
                "page_engagement": 0,
                "post_engagement": 0,
                "post_reactions": 0,
                "post_comments": 0,
                "post_saves": 0,
                "post_shares": 0,
                "previous": {
                    "spend": 0,
                    "link_clicks": 0,
                    "conversions": 0,
                    "add_to_cart": 0,
                    "purchase": 0,
                },
            }
        )

    row = rows[0]
    totals = {
        "impressions": _or_zero(_to_number(row.get("total_impressions"))),
        "link_clicks": _or_zero(_to_number(row.get("total_link_clicks"))),
        "spend": _or_zero(_to_number(row.get("total_spend"))),
        "conversions": _or_zero(_to_number(row.get("total_conversions"))),
        "conversion_value": _or_zero(_to_number(row.get("total_conversion_value"))),
        "add_to_cart": _or_zero(_to_number(row.get("total_add_to_cart"))),
        "purchase": _or_zero(_to_number(row.get("total_purchase"))),
        "purchase_value": _or_zero(_to_number(row.get("total_purchase_value"))),
        "outbound_clicks": _or_zero(_to_number(row.get("total_outbound_clicks"))),
        "page_engagement": _or_zero(_to_number(row.get("total_page_engagement"))),
        "post_engagement": _or_zero(_to_number(row.get("total_post_engagement"))),
        "post_reactions": _or_zero(_to_number(row.get("total_post_reactions"))),
        "post_comments": _or_zero(_to_number(row.get("total_post_comments"))),
        "post_saves": _or_zero(_to_number(row.get("total_post_saves"))),
        "post_shares": _or_zero(_to_number(row.get("total_post_shares"))),
        "previous": {
            "spend": _or_zero(_to_number(row.get("total_previous_spend"))),
            "link_clicks": _or_zero(
                _to_number(row.get("total_previous_link_clicks"))
            ),
            "conversions": _or_zero(
                _to_number(row.get("total_previous_conversions"))
            ),
            "add_to_cart": _or_zero(
                _to_number(row.get("total_previous_add_to_cart"))
            ),
            "purchase": _or_zero(_to_number(row.get("total_previous_purchase"))),
        },
    }
    return _calculate_rates(totals)


def _calculate_rates(totals: dict[str, Any]) -> dict[str, Any]:
    """Calculate ratio metrics from additive totals."""
    totals["ctr"] = _safe_divide(totals["link_clicks"], totals["impressions"])
    totals["cpc"] = _safe_divide(totals["spend"], totals["link_clicks"])
    totals["cpm"] = _safe_divide(totals["spend"] * 1000, totals["impressions"])
    totals["cpa"] = _safe_divide(totals["spend"], totals["conversions"])
    totals["roas"] = _safe_divide(totals["conversion_value"], totals["spend"])
    totals["cost_per_add_to_cart"] = _safe_divide(
        totals["spend"],
        totals["add_to_cart"],
    )
    totals["cost_per_purchase"] = _safe_divide(totals["spend"], totals["purchase"])
    totals["purchase_roas"] = _safe_divide(totals["purchase_value"], totals["spend"])
    previous = totals.get("previous")
    if isinstance(previous, dict):
        previous["cpc"] = _safe_divide(previous["spend"], previous["link_clicks"])
        previous["cpa"] = _safe_divide(previous["spend"], previous["conversions"])
        previous["cost_per_add_to_cart"] = _safe_divide(
            previous["spend"],
            previous["add_to_cart"],
        )
        previous["cost_per_purchase"] = _safe_divide(
            previous["spend"],
            previous["purchase"],
        )
        totals["delta"] = {
            "spend": totals["spend"] - previous["spend"],
            "link_clicks": totals["link_clicks"] - previous["link_clicks"],
            "conversions": totals["conversions"] - previous["conversions"],
            "add_to_cart": totals["add_to_cart"] - previous["add_to_cart"],
            "purchase": totals["purchase"] - previous["purchase"],
            "cpc": _subtract_optional(totals["cpc"], previous["cpc"]),
            "cpa": _subtract_optional(totals["cpa"], previous["cpa"]),
            "cost_per_purchase": _subtract_optional(
                totals["cost_per_purchase"],
                previous["cost_per_purchase"],
            ),
        }
    return totals


def _format_date(value: Any) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _first_value(rows: list[dict[str, Any]], key: str) -> Any:
    for row in rows:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _to_number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return value
    return float(value)


def _or_zero(value: float | int | None) -> float | int:
    return value if value is not None else 0


def _safe_divide(numerator: float | int, denominator: float | int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _subtract_optional(
    value: float | int | None,
    previous_value: float | int | None,
) -> float | int | None:
    if value is None or previous_value is None:
        return None
    return value - previous_value
