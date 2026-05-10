"""Google Ads API connector."""

from __future__ import annotations

from typing import Any

from src.connectors.base import BaseAdsConnector


AD_LEVEL_QUERY = """
SELECT
  segments.date,
  customer.id,
  customer.descriptive_name,
  customer.currency_code,
  campaign.id,
  campaign.name,
  campaign.status,
  campaign.advertising_channel_type,
  ad_group.id,
  ad_group.name,
  ad_group.status,
  ad_group_ad.ad.id,
  ad_group_ad.ad.name,
  ad_group_ad.status,
  ad_group_ad.ad.type,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value,
  metrics.ctr,
  metrics.average_cpc,
  metrics.average_cpm,
  metrics.cost_per_conversion
FROM ad_group_ad
WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
  AND metrics.impressions > 0
"""

KEYWORD_LEVEL_QUERY = """
SELECT
  segments.date,
  customer.id,
  customer.descriptive_name,
  customer.currency_code,
  campaign.id,
  campaign.name,
  campaign.status,
  campaign.advertising_channel_type,
  ad_group.id,
  ad_group.name,
  ad_group.status,
  ad_group_criterion.criterion_id,
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type,
  ad_group_criterion.status,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value,
  metrics.ctr,
  metrics.average_cpc,
  metrics.average_cpm,
  metrics.cost_per_conversion
FROM keyword_view
WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
  AND metrics.impressions > 0
"""

SEARCH_TERM_LEVEL_QUERY = """
SELECT
  segments.date,
  customer.id,
  customer.descriptive_name,
  customer.currency_code,
  campaign.id,
  campaign.name,
  campaign.status,
  campaign.advertising_channel_type,
  ad_group.id,
  ad_group.name,
  ad_group.status,
  search_term_view.search_term,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value,
  metrics.ctr,
  metrics.average_cpc,
  metrics.average_cpm,
  metrics.cost_per_conversion
FROM search_term_view
WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
  AND metrics.impressions > 0
"""


class GoogleAdsConnector(BaseAdsConnector):
    """Fetch daily Google Ads performance rows."""

    platform_name = "google_ads"

    def __init__(
        self,
        developer_token: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        login_customer_id: str | None = None,
    ) -> None:
        if not developer_token:
            raise ValueError("Google Ads developer token is required.")
        if not client_id:
            raise ValueError("Google Ads client ID is required.")
        if not client_secret:
            raise ValueError("Google Ads client secret is required.")
        if not refresh_token:
            raise ValueError("Google Ads refresh token is required.")

        from google.ads.googleads.client import GoogleAdsClient

        credentials: dict[str, Any] = {
            "developer_token": developer_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "use_proto_plus": True,
        }
        if login_customer_id:
            credentials["login_customer_id"] = login_customer_id

        self.client = GoogleAdsClient.load_from_dict(credentials)
        self.google_ads_service = self.client.get_service("GoogleAdsService")

    def fetch_daily_report(
        self,
        customer_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """Fetch ad-level and keyword-level daily rows for a customer."""
        customer_id = customer_id.replace("-", "")
        ad_rows = self._run_query(
            customer_id=customer_id,
            query=AD_LEVEL_QUERY.format(start_date=start_date, end_date=end_date),
            report_level="ad",
        )
        keyword_rows = self._run_query(
            customer_id=customer_id,
            query=KEYWORD_LEVEL_QUERY.format(start_date=start_date, end_date=end_date),
            report_level="keyword",
        )
        search_term_rows = self._run_query(
            customer_id=customer_id,
            query=SEARCH_TERM_LEVEL_QUERY.format(start_date=start_date, end_date=end_date),
            report_level="search_term",
        )
        return ad_rows + keyword_rows + search_term_rows

    def _run_query(
        self,
        customer_id: str,
        query: str,
        report_level: str,
    ) -> list[dict]:
        """Run one GAQL query and flatten response rows."""
        rows: list[dict] = []
        stream = self.google_ads_service.search_stream(
            customer_id=customer_id,
            query=query,
        )
        for batch in stream:
            for row in batch.results:
                rows.append(_flatten_google_ads_row(row, report_level=report_level))
        return rows


def _flatten_google_ads_row(row: Any, report_level: str) -> dict[str, Any]:
    """Flatten a Google Ads API row into JSON-serializable primitives."""
    metrics = row.metrics
    campaign = row.campaign
    ad_group = row.ad_group
    flattened: dict[str, Any] = {
        "date": str(row.segments.date),
        "report_level": report_level,
        "customer_id": str(row.customer.id),
        "account_name": row.customer.descriptive_name,
        "currency": row.customer.currency_code,
        "campaign_id": str(campaign.id),
        "campaign_name": campaign.name,
        "campaign_status": campaign.status.name,
        "campaign_channel_type": campaign.advertising_channel_type.name,
        "ad_group_id": str(ad_group.id),
        "ad_group_name": ad_group.name,
        "ad_group_status": ad_group.status.name,
        "impressions": int(metrics.impressions),
        "clicks": int(metrics.clicks),
        "spend": _micros_to_units(metrics.cost_micros),
        "conversions": float(metrics.conversions),
        "conversion_value": float(metrics.conversions_value),
        "ctr": float(metrics.ctr),
        "cpc": _micros_to_units(metrics.average_cpc),
        "cpm": _micros_to_units(metrics.average_cpm),
        "cpa": _micros_to_units(metrics.cost_per_conversion),
    }

    if report_level == "ad":
        ad = row.ad_group_ad.ad
        flattened.update(
            {
                "ad_id": str(ad.id),
                "ad_name": ad.name,
                "ad_status": row.ad_group_ad.status.name,
                "ad_type": ad.type_.name,
            }
        )
    elif report_level == "keyword":
        criterion = row.ad_group_criterion
        flattened.update(
            {
                "criterion_id": str(criterion.criterion_id),
                "keyword_text": criterion.keyword.text,
                "keyword_match_type": criterion.keyword.match_type.name,
                "criterion_status": criterion.status.name,
            }
        )
    elif report_level == "search_term":
        flattened["search_term"] = row.search_term_view.search_term

    return flattened


def _micros_to_units(value: int | float | None) -> float:
    """Convert Google Ads micros to account currency units."""
    if value in (None, ""):
        return 0.0
    return float(value) / 1_000_000
