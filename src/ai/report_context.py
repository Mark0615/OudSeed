"""Build AI-ready report context from reporting marts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from google.cloud import bigquery

from src.destinations.bigquery import BigQueryDestination
from src.ai.report_diagnostics import build_report_diagnostics


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
    previous_cpc_field: str
    previous_cpa_field: str
    previous_roas_field: str
    spend_delta_field: str
    clicks_delta_field: str
    conversions_delta_field: str
    cpc_delta_field: str
    cpa_delta_field: str
    roas_delta_field: str
    spend_rate_field: str
    clicks_rate_field: str
    conversions_rate_field: str
    cpc_rate_field: str
    cpa_rate_field: str
    roas_rate_field: str


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
        previous_cpc_field="previous_week_cpc",
        previous_cpa_field="previous_week_cpa",
        previous_roas_field="previous_week_roas",
        spend_delta_field="spend_wow",
        clicks_delta_field="link_clicks_wow",
        conversions_delta_field="conversions_wow",
        cpc_delta_field="cpc_wow",
        cpa_delta_field="cpa_wow",
        roas_delta_field="roas_wow",
        spend_rate_field="spend_wow_rate",
        clicks_rate_field="link_clicks_wow_rate",
        conversions_rate_field="conversions_wow_rate",
        cpc_rate_field="cpc_wow_rate",
        cpa_rate_field="cpa_wow_rate",
        roas_rate_field="roas_wow_rate",
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
        previous_cpc_field="previous_month_cpc",
        previous_cpa_field="previous_month_cpa",
        previous_roas_field="previous_month_roas",
        spend_delta_field="spend_mom",
        clicks_delta_field="link_clicks_mom",
        conversions_delta_field="conversions_mom",
        cpc_delta_field="cpc_mom",
        cpa_delta_field="cpa_mom",
        roas_delta_field="roas_mom",
        spend_rate_field="spend_mom_rate",
        clicks_rate_field="link_clicks_mom_rate",
        conversions_rate_field="conversions_mom_rate",
        cpc_rate_field="cpc_mom_rate",
        cpa_rate_field="cpa_mom_rate",
        roas_rate_field="roas_mom_rate",
    ),
}


def build_report_context(
    destination: BigQueryDestination,
    report_type: ReportType,
    workspace_id: str,
    client_id: str,
    period_start_date: str,
    account_id: str | None = None,
    account_ids: list[str] | None = None,
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

    scoped_account_ids = _normalize_account_ids(account_id, account_ids)
    if len(scoped_account_ids) == 1:
        filters.append("account_id = @account_id")
        query_parameters.append(
            bigquery.ScalarQueryParameter("account_id", "STRING", scoped_account_ids[0])
        )
    elif scoped_account_ids:
        filters.append("account_id IN UNNEST(@account_ids)")
        query_parameters.append(
            bigquery.ArrayQueryParameter("account_ids", "STRING", scoped_account_ids)
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
        {config.previous_cpc_field} AS previous_cpc,
        {config.previous_cpa_field} AS previous_cpa,
        {config.previous_roas_field} AS previous_roas,
        {config.spend_delta_field} AS spend_delta,
        {config.clicks_delta_field} AS link_clicks_delta,
        {config.conversions_delta_field} AS conversions_delta,
        {config.cpc_delta_field} AS cpc_delta,
        {config.cpa_delta_field} AS cpa_delta,
        {config.roas_delta_field} AS roas_delta,
        {config.spend_rate_field} AS spend_delta_rate,
        {config.clicks_rate_field} AS link_clicks_delta_rate,
        {config.conversions_rate_field} AS conversions_delta_rate,
        {config.cpc_rate_field} AS cpc_delta_rate,
        {config.cpa_rate_field} AS cpa_delta_rate,
        {config.roas_rate_field} AS roas_delta_rate
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
    period_end_date = _first_value(campaigns, "period_end_date")
    previous_totals = _fetch_previous_period_totals(
        destination=destination,
        config=config,
        workspace_id=workspace_id,
        client_id=client_id,
        period_start_date=period_start_date,
        account_ids=scoped_account_ids,
    )
    details = _fetch_performance_details(
        destination=destination,
        workspace_id=workspace_id,
        client_id=client_id,
        account_id=account_id,
        account_ids=scoped_account_ids,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        limit=limit,
    )

    context = {
        "report_type": report_type,
        "comparison": config.comparison_label,
        "workspace_id": workspace_id,
        "client_id": client_id,
        "account_id": account_id,
        "account_ids": scoped_account_ids,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "totals": _extract_totals(rows, previous_totals=previous_totals),
        "campaigns": campaigns,
        "ad_groups": details["ad_groups"],
        "ads": details["ads"],
        "keywords": details["keywords"],
        "search_terms": details["search_terms"],
    }
    context["diagnostics"] = build_report_diagnostics(context)
    return context


def _fetch_performance_details(
    destination: BigQueryDestination,
    workspace_id: str,
    client_id: str,
    account_id: str | None,
    account_ids: list[str],
    period_start_date: str,
    period_end_date: str | None,
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch ad group, ad, and keyword details for AI recommendations."""
    empty_details: dict[str, list[dict[str, Any]]] = {
        "ad_groups": [],
        "ads": [],
        "keywords": [],
        "search_terms": [],
    }
    if not period_end_date:
        return empty_details

    return {
        "ad_groups": _fetch_ad_group_breakdown(
            destination=destination,
            workspace_id=workspace_id,
            client_id=client_id,
            account_id=account_id,
            account_ids=account_ids,
            period_start_date=period_start_date,
            period_end_date=period_end_date,
            limit=limit,
        ),
        "ads": _fetch_ad_breakdown(
            destination=destination,
            workspace_id=workspace_id,
            client_id=client_id,
            account_id=account_id,
            account_ids=account_ids,
            period_start_date=period_start_date,
            period_end_date=period_end_date,
            limit=limit,
        ),
        "keywords": _fetch_google_keyword_breakdown(
            destination=destination,
            workspace_id=workspace_id,
            client_id=client_id,
            account_id=account_id,
            account_ids=account_ids,
            period_start_date=period_start_date,
            period_end_date=period_end_date,
            limit=limit,
        ),
        "search_terms": _fetch_google_search_term_breakdown(
            destination=destination,
            workspace_id=workspace_id,
            client_id=client_id,
            account_id=account_id,
            account_ids=account_ids,
            period_start_date=period_start_date,
            period_end_date=period_end_date,
            limit=limit,
        ),
    }


def _fetch_ad_group_breakdown(
    destination: BigQueryDestination,
    workspace_id: str,
    client_id: str,
    account_id: str | None,
    account_ids: list[str],
    period_start_date: str,
    period_end_date: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Return top ad group rows for the report period."""
    filters, parameters = _detail_filters(
        workspace_id=workspace_id,
        client_id=client_id,
        account_id=account_id,
        account_ids=account_ids,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        limit=limit,
    )
    query = f"""
    SELECT
      platform,
      account_id,
      ANY_VALUE(account_name) AS account_name,
      campaign_id,
      ANY_VALUE(campaign_name) AS campaign_name,
      ad_group_id,
      ANY_VALUE(ad_group_name) AS ad_group_name,
      SUM(impressions) AS impressions,
      SUM(link_clicks) AS link_clicks,
      SUM(spend) AS spend,
      SUM(conversions) AS conversions,
      SUM(conversion_value) AS conversion_value,
      SUM(add_to_cart) AS add_to_cart,
      SUM(purchase) AS purchase,
      SUM(purchase_value) AS purchase_value,
      SAFE_DIVIDE(SUM(link_clicks), SUM(impressions)) AS ctr,
      SAFE_DIVIDE(SUM(spend), SUM(link_clicks)) AS cpc,
      SAFE_DIVIDE(SUM(spend) * 1000, SUM(impressions)) AS cpm,
      SAFE_DIVIDE(SUM(spend), SUM(conversions)) AS cpa,
      SAFE_DIVIDE(SUM(conversion_value), SUM(spend)) AS roas,
      SUM(post_engagement) AS post_engagement,
      SUM(post_reactions) AS post_reactions,
      SUM(post_comments) AS post_comments,
      SUM(post_saves) AS post_saves,
      SUM(post_shares) AS post_shares
    FROM `{destination._table_id("vw_looker_ads_ad_daily")}`
    WHERE {" AND ".join(filters)}
      AND ad_group_id IS NOT NULL
    GROUP BY platform, account_id, campaign_id, ad_group_id
    ORDER BY spend DESC
    LIMIT @limit
    """
    return [_normalize_detail_row(row) for row in destination.query_rows(query, parameters)]


def _fetch_ad_breakdown(
    destination: BigQueryDestination,
    workspace_id: str,
    client_id: str,
    account_id: str | None,
    account_ids: list[str],
    period_start_date: str,
    period_end_date: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Return top ad/creative rows for the report period."""
    filters, parameters = _detail_filters(
        workspace_id=workspace_id,
        client_id=client_id,
        account_id=account_id,
        account_ids=account_ids,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        limit=limit,
    )
    query = f"""
    SELECT
      platform,
      account_id,
      ANY_VALUE(account_name) AS account_name,
      campaign_id,
      ANY_VALUE(campaign_name) AS campaign_name,
      ad_group_id,
      ANY_VALUE(ad_group_name) AS ad_group_name,
      ad_id,
      ANY_VALUE(ad_name) AS ad_name,
      SUM(impressions) AS impressions,
      SUM(link_clicks) AS link_clicks,
      SUM(spend) AS spend,
      SUM(conversions) AS conversions,
      SUM(conversion_value) AS conversion_value,
      SUM(add_to_cart) AS add_to_cart,
      SUM(purchase) AS purchase,
      SUM(purchase_value) AS purchase_value,
      SAFE_DIVIDE(SUM(link_clicks), SUM(impressions)) AS ctr,
      SAFE_DIVIDE(SUM(spend), SUM(link_clicks)) AS cpc,
      SAFE_DIVIDE(SUM(spend) * 1000, SUM(impressions)) AS cpm,
      SAFE_DIVIDE(SUM(spend), SUM(conversions)) AS cpa,
      SAFE_DIVIDE(SUM(conversion_value), SUM(spend)) AS roas,
      SUM(post_engagement) AS post_engagement,
      SUM(post_reactions) AS post_reactions,
      SUM(post_comments) AS post_comments,
      SUM(post_saves) AS post_saves,
      SUM(post_shares) AS post_shares
    FROM `{destination._table_id("vw_looker_ads_ad_daily")}`
    WHERE {" AND ".join(filters)}
      AND ad_id IS NOT NULL
    GROUP BY platform, account_id, campaign_id, ad_group_id, ad_id
    ORDER BY spend DESC
    LIMIT @limit
    """
    return [_normalize_detail_row(row) for row in destination.query_rows(query, parameters)]


def _fetch_google_keyword_breakdown(
    destination: BigQueryDestination,
    workspace_id: str,
    client_id: str,
    account_id: str | None,
    account_ids: list[str],
    period_start_date: str,
    period_end_date: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Return top Google Ads keyword rows from raw keyword-level payloads."""
    filters, parameters = _detail_filters(
        workspace_id=workspace_id,
        client_id=client_id,
        account_id=account_id,
        account_ids=account_ids,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        limit=limit,
    )
    filters.extend(["platform = 'google_ads'", "report_level = 'keyword'"])
    query = f"""
    SELECT
      platform,
      account_id,
      JSON_VALUE(raw_payload, '$.account_name') AS account_name,
      JSON_VALUE(raw_payload, '$.campaign_id') AS campaign_id,
      ANY_VALUE(JSON_VALUE(raw_payload, '$.campaign_name')) AS campaign_name,
      JSON_VALUE(raw_payload, '$.ad_group_id') AS ad_group_id,
      ANY_VALUE(JSON_VALUE(raw_payload, '$.ad_group_name')) AS ad_group_name,
      JSON_VALUE(raw_payload, '$.criterion_id') AS criterion_id,
      ANY_VALUE(JSON_VALUE(raw_payload, '$.keyword_text')) AS keyword_text,
      ANY_VALUE(JSON_VALUE(raw_payload, '$.keyword_match_type')) AS keyword_match_type,
      SUM(CAST(JSON_VALUE(raw_payload, '$.impressions') AS INT64)) AS impressions,
      SUM(CAST(JSON_VALUE(raw_payload, '$.clicks') AS INT64)) AS link_clicks,
      SUM(CAST(JSON_VALUE(raw_payload, '$.spend') AS FLOAT64)) AS spend,
      SUM(CAST(JSON_VALUE(raw_payload, '$.conversions') AS FLOAT64)) AS conversions,
      SUM(CAST(JSON_VALUE(raw_payload, '$.conversion_value') AS FLOAT64)) AS conversion_value,
      SAFE_DIVIDE(
        SUM(CAST(JSON_VALUE(raw_payload, '$.clicks') AS INT64)),
        SUM(CAST(JSON_VALUE(raw_payload, '$.impressions') AS INT64))
      ) AS ctr,
      SAFE_DIVIDE(
        SUM(CAST(JSON_VALUE(raw_payload, '$.spend') AS FLOAT64)),
        SUM(CAST(JSON_VALUE(raw_payload, '$.clicks') AS INT64))
      ) AS cpc,
      SAFE_DIVIDE(
        SUM(CAST(JSON_VALUE(raw_payload, '$.spend') AS FLOAT64)) * 1000,
        SUM(CAST(JSON_VALUE(raw_payload, '$.impressions') AS INT64))
      ) AS cpm,
      SAFE_DIVIDE(
        SUM(CAST(JSON_VALUE(raw_payload, '$.spend') AS FLOAT64)),
        SUM(CAST(JSON_VALUE(raw_payload, '$.conversions') AS FLOAT64))
      ) AS cpa,
      SAFE_DIVIDE(
        SUM(CAST(JSON_VALUE(raw_payload, '$.conversion_value') AS FLOAT64)),
        SUM(CAST(JSON_VALUE(raw_payload, '$.spend') AS FLOAT64))
      ) AS roas
    FROM `{destination._table_id("raw_google_ads_daily")}`
    WHERE {" AND ".join(filters)}
    GROUP BY platform, account_id, account_name, campaign_id, ad_group_id, criterion_id
    ORDER BY spend DESC
    LIMIT @limit
    """
    return [_normalize_detail_row(row) for row in destination.query_rows(query, parameters)]


def _fetch_google_search_term_breakdown(
    destination: BigQueryDestination,
    workspace_id: str,
    client_id: str,
    account_id: str | None,
    account_ids: list[str],
    period_start_date: str,
    period_end_date: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Return top Google Ads search term rows from raw search-term payloads."""
    filters, parameters = _detail_filters(
        workspace_id=workspace_id,
        client_id=client_id,
        account_id=account_id,
        account_ids=account_ids,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        limit=limit,
    )
    filters.extend(["platform = 'google_ads'", "report_level = 'search_term'"])
    query = f"""
    SELECT
      platform,
      account_id,
      JSON_VALUE(raw_payload, '$.account_name') AS account_name,
      JSON_VALUE(raw_payload, '$.campaign_id') AS campaign_id,
      ANY_VALUE(JSON_VALUE(raw_payload, '$.campaign_name')) AS campaign_name,
      JSON_VALUE(raw_payload, '$.ad_group_id') AS ad_group_id,
      ANY_VALUE(JSON_VALUE(raw_payload, '$.ad_group_name')) AS ad_group_name,
      JSON_VALUE(raw_payload, '$.search_term') AS search_term,
      SUM(CAST(JSON_VALUE(raw_payload, '$.impressions') AS INT64)) AS impressions,
      SUM(CAST(JSON_VALUE(raw_payload, '$.clicks') AS INT64)) AS link_clicks,
      SUM(CAST(JSON_VALUE(raw_payload, '$.spend') AS FLOAT64)) AS spend,
      SUM(CAST(JSON_VALUE(raw_payload, '$.conversions') AS FLOAT64)) AS conversions,
      SUM(CAST(JSON_VALUE(raw_payload, '$.conversion_value') AS FLOAT64)) AS conversion_value,
      SAFE_DIVIDE(
        SUM(CAST(JSON_VALUE(raw_payload, '$.clicks') AS INT64)),
        SUM(CAST(JSON_VALUE(raw_payload, '$.impressions') AS INT64))
      ) AS ctr,
      SAFE_DIVIDE(
        SUM(CAST(JSON_VALUE(raw_payload, '$.spend') AS FLOAT64)),
        SUM(CAST(JSON_VALUE(raw_payload, '$.clicks') AS INT64))
      ) AS cpc,
      SAFE_DIVIDE(
        SUM(CAST(JSON_VALUE(raw_payload, '$.spend') AS FLOAT64)) * 1000,
        SUM(CAST(JSON_VALUE(raw_payload, '$.impressions') AS INT64))
      ) AS cpm,
      SAFE_DIVIDE(
        SUM(CAST(JSON_VALUE(raw_payload, '$.spend') AS FLOAT64)),
        SUM(CAST(JSON_VALUE(raw_payload, '$.conversions') AS FLOAT64))
      ) AS cpa,
      SAFE_DIVIDE(
        SUM(CAST(JSON_VALUE(raw_payload, '$.conversion_value') AS FLOAT64)),
        SUM(CAST(JSON_VALUE(raw_payload, '$.spend') AS FLOAT64))
      ) AS roas
    FROM `{destination._table_id("raw_google_ads_daily")}`
    WHERE {" AND ".join(filters)}
    GROUP BY platform, account_id, account_name, campaign_id, ad_group_id, search_term
    ORDER BY spend DESC
    LIMIT @limit
    """
    return [_normalize_detail_row(row) for row in destination.query_rows(query, parameters)]


def _detail_filters(
    workspace_id: str,
    client_id: str,
    account_id: str | None,
    account_ids: list[str],
    period_start_date: str,
    period_end_date: str,
    limit: int,
) -> tuple[list[str], list[bigquery.ScalarQueryParameter]]:
    """Return shared filters and query parameters for detail breakdowns."""
    filters = [
        "date BETWEEN @period_start_date AND @period_end_date",
        "workspace_id = @workspace_id",
        "client_id = @client_id",
    ]
    parameters: list[bigquery.ScalarQueryParameter] = [
        bigquery.ScalarQueryParameter("period_start_date", "DATE", period_start_date),
        bigquery.ScalarQueryParameter("period_end_date", "DATE", period_end_date),
        bigquery.ScalarQueryParameter("workspace_id", "STRING", workspace_id),
        bigquery.ScalarQueryParameter("client_id", "STRING", client_id),
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
    ]
    scoped_account_ids = _normalize_account_ids(account_id, account_ids)
    if len(scoped_account_ids) == 1:
        filters.append("account_id = @account_id")
        parameters.append(
            bigquery.ScalarQueryParameter("account_id", "STRING", scoped_account_ids[0])
        )
    elif scoped_account_ids:
        filters.append("account_id IN UNNEST(@account_ids)")
        parameters.append(
            bigquery.ArrayQueryParameter("account_ids", "STRING", scoped_account_ids)
        )
    return filters, parameters


def _normalize_account_ids(
    account_id: str | None,
    account_ids: list[str] | None,
) -> list[str]:
    """Return de-duplicated account ids from single and multi-account filters."""
    values: list[str] = []
    if account_id:
        values.append(account_id)
    if account_ids:
        values.extend(account_ids)
    return list(dict.fromkeys(str(value) for value in values if value))


def _fetch_previous_period_totals(
    destination: BigQueryDestination,
    config: ReportMetricConfig,
    workspace_id: str,
    client_id: str,
    period_start_date: str,
    account_ids: list[str],
) -> dict[str, Any] | None:
    """Fetch complete previous-period totals independent of current campaigns."""
    previous_start_date = _previous_period_start_date(
        period_start_date=period_start_date,
        start_field=config.start_field,
    )
    filters = [
        f"{config.start_field} = @previous_start_date",
        "workspace_id = @workspace_id",
        "client_id = @client_id",
    ]
    parameters: list[bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter] = [
        bigquery.ScalarQueryParameter("previous_start_date", "DATE", previous_start_date),
        bigquery.ScalarQueryParameter("workspace_id", "STRING", workspace_id),
        bigquery.ScalarQueryParameter("client_id", "STRING", client_id),
    ]
    if len(account_ids) == 1:
        filters.append("account_id = @account_id")
        parameters.append(bigquery.ScalarQueryParameter("account_id", "STRING", account_ids[0]))
    elif account_ids:
        filters.append("account_id IN UNNEST(@account_ids)")
        parameters.append(bigquery.ArrayQueryParameter("account_ids", "STRING", account_ids))

    query = f"""
    SELECT
      SUM(impressions) AS impressions,
      SUM(link_clicks) AS link_clicks,
      SUM(spend) AS spend,
      SUM(conversions) AS conversions,
      SUM(conversion_value) AS conversion_value,
      SUM(add_to_cart) AS add_to_cart,
      SUM(purchase) AS purchase,
      SUM(purchase_value) AS purchase_value
    FROM `{destination._table_id(config.view_name)}`
    WHERE {" AND ".join(filters)}
    """
    rows = destination.query_rows(query, query_parameters=parameters)
    if not rows:
        return None

    row = rows[0]
    previous = {
        "impressions": _or_zero(_to_number(row.get("impressions"))),
        "link_clicks": _or_zero(_to_number(row.get("link_clicks"))),
        "spend": _or_zero(_to_number(row.get("spend"))),
        "conversions": _or_zero(_to_number(row.get("conversions"))),
        "conversion_value": _or_zero(_to_number(row.get("conversion_value"))),
        "add_to_cart": _or_zero(_to_number(row.get("add_to_cart"))),
        "purchase": _or_zero(_to_number(row.get("purchase"))),
        "purchase_value": _or_zero(_to_number(row.get("purchase_value"))),
    }
    previous["cpc"] = _safe_divide(previous["spend"], previous["link_clicks"])
    previous["cpa"] = _safe_divide(previous["spend"], previous["conversions"])
    previous["cost_per_add_to_cart"] = _safe_divide(
        previous["spend"],
        previous["add_to_cart"],
    )
    previous["cost_per_purchase"] = _safe_divide(previous["spend"], previous["purchase"])
    previous["roas"] = _safe_divide(previous["conversion_value"], previous["spend"])
    return previous


def _previous_period_start_date(period_start_date: str, start_field: str) -> str:
    """Return previous week/month start date for report comparison."""
    current = date.fromisoformat(period_start_date)
    if start_field == "week_start_date":
        return (current - timedelta(days=7)).isoformat()

    first_of_current_month = current.replace(day=1)
    last_day_previous_month = first_of_current_month - timedelta(days=1)
    return last_day_previous_month.replace(day=1).isoformat()


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
        "previous_cpc": _to_number(row.get("previous_cpc")),
        "previous_cpa": _to_number(row.get("previous_cpa")),
        "previous_roas": _to_number(row.get("previous_roas")),
        "spend_delta": _to_number(row.get("spend_delta")),
        "link_clicks_delta": _to_number(row.get("link_clicks_delta")),
        "conversions_delta": _to_number(row.get("conversions_delta")),
        "cpc_delta": _to_number(row.get("cpc_delta")),
        "cpa_delta": _to_number(row.get("cpa_delta")),
        "roas_delta": _to_number(row.get("roas_delta")),
        "spend_delta_rate": _to_number(row.get("spend_delta_rate")),
        "link_clicks_delta_rate": _to_number(row.get("link_clicks_delta_rate")),
        "conversions_delta_rate": _to_number(row.get("conversions_delta_rate")),
        "cpc_delta_rate": _to_number(row.get("cpc_delta_rate")),
        "cpa_delta_rate": _to_number(row.get("cpa_delta_rate")),
        "roas_delta_rate": _to_number(row.get("roas_delta_rate")),
    }


def _normalize_detail_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize detailed BigQuery rows into JSON-friendly report fields."""
    return {
        "platform": row.get("platform"),
        "account_id": row.get("account_id"),
        "account_name": row.get("account_name"),
        "campaign_id": row.get("campaign_id"),
        "campaign_name": row.get("campaign_name"),
        "ad_group_id": row.get("ad_group_id"),
        "ad_group_name": row.get("ad_group_name"),
        "ad_id": row.get("ad_id"),
        "ad_name": row.get("ad_name"),
        "criterion_id": row.get("criterion_id"),
        "keyword_text": row.get("keyword_text"),
        "keyword_match_type": row.get("keyword_match_type"),
        "search_term": row.get("search_term"),
        "impressions": _to_number(row.get("impressions")),
        "link_clicks": _to_number(row.get("link_clicks")),
        "spend": _to_number(row.get("spend")),
        "conversions": _to_number(row.get("conversions")),
        "conversion_value": _to_number(row.get("conversion_value")),
        "add_to_cart": _to_number(row.get("add_to_cart")),
        "purchase": _to_number(row.get("purchase")),
        "purchase_value": _to_number(row.get("purchase_value")),
        "ctr": _to_number(row.get("ctr")),
        "cpc": _to_number(row.get("cpc")),
        "cpm": _to_number(row.get("cpm")),
        "cpa": _to_number(row.get("cpa")),
        "roas": _to_number(row.get("roas")),
        "post_engagement": _to_number(row.get("post_engagement")),
        "post_reactions": _to_number(row.get("post_reactions")),
        "post_comments": _to_number(row.get("post_comments")),
        "post_saves": _to_number(row.get("post_saves")),
        "post_shares": _to_number(row.get("post_shares")),
    }


def _extract_totals(
    rows: list[dict[str, Any]],
    previous_totals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract full-period totals from window fields returned by BigQuery."""
    if not rows:
        totals = _calculate_rates(
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
        if previous_totals:
            totals["previous"] = previous_totals
            totals["delta"] = _calculate_delta(totals, previous_totals)
        return totals

    row = rows[0]
    default_previous = {
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
    }
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
        "previous": previous_totals or default_previous,
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
        previous.setdefault("cpc", _safe_divide(previous["spend"], previous["link_clicks"]))
        previous.setdefault("cpa", _safe_divide(previous["spend"], previous["conversions"]))
        previous.setdefault(
            "cost_per_add_to_cart",
            _safe_divide(previous["spend"], previous["add_to_cart"]),
        )
        previous.setdefault(
            "cost_per_purchase",
            _safe_divide(previous["spend"], previous["purchase"]),
        )
        totals["delta"] = _calculate_delta(totals, previous)
    return totals


def _calculate_delta(totals: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    """Calculate current-vs-previous total deltas."""
    return {
        "spend": totals["spend"] - previous["spend"],
        "link_clicks": totals["link_clicks"] - previous["link_clicks"],
        "conversions": totals["conversions"] - previous["conversions"],
        "conversion_value": totals["conversion_value"] - previous.get("conversion_value", 0),
        "add_to_cart": totals["add_to_cart"] - previous["add_to_cart"],
        "purchase": totals["purchase"] - previous["purchase"],
        "purchase_value": totals["purchase_value"] - previous.get("purchase_value", 0),
        "cpc": _subtract_optional(totals["cpc"], previous.get("cpc")),
        "cpa": _subtract_optional(totals["cpa"], previous.get("cpa")),
        "cost_per_purchase": _subtract_optional(
            totals["cost_per_purchase"],
            previous.get("cost_per_purchase"),
        ),
        "roas": _subtract_optional(totals["roas"], previous.get("roas")),
    }


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
