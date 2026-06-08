"""Read a last-7/30-day preview of synced ad data from BigQuery.

This powers the onboarding "Preview" step: after the customer picks which
accounts to sync, we show recent spend and top campaigns so they can confirm
the data looks right. It reads the staged ``unified_ads_daily`` table, scoped to
the workspace (tenant isolation) and the selected accounts.

The read is best-effort: the route wraps it so a missing/empty table or a
BigQuery error degrades to an empty-state card rather than breaking the page.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol

from google.cloud import bigquery

UNIFIED_TABLE = "unified_ads_daily"
SHORT_WINDOW_DAYS = 7
LONG_WINDOW_DAYS = 30
TOP_CAMPAIGNS = 5


class PreviewSource(Protocol):
    """Minimal BigQuery surface the preview needs (satisfied by BigQueryDestination)."""

    def qualified_table(self, table_name: str) -> str: ...

    def query_rows(
        self,
        sql: str,
        query_parameters: list[Any] | None = None,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class PreviewCampaign:
    """One campaign's totals within a window."""

    platform: str
    campaign_name: str
    spend: float
    impressions: int
    clicks: int
    conversions: float


@dataclass(frozen=True)
class PreviewWindow:
    """Aggregated totals + top campaigns for one time window."""

    window_days: int
    has_data: bool = False
    spend: float = 0.0
    impressions: int = 0
    clicks: int = 0
    conversions: float = 0.0
    currency: str | None = None
    top_campaigns: tuple[PreviewCampaign, ...] = ()


@dataclass(frozen=True)
class PreviewData:
    """Both preview windows for the selected accounts."""

    short: PreviewWindow
    long: PreviewWindow

    @property
    def has_data(self) -> bool:
        return self.short.has_data or self.long.has_data


def _num(value: Any) -> float:
    return float(value) if value is not None else 0.0


def _int(value: Any) -> int:
    return int(value) if value is not None else 0


def _window_from_rows(
    rows: list[dict[str, Any]],
    *,
    window_days: int,
    spend_key: str,
    impr_key: str,
    clicks_key: str,
    conv_key: str,
) -> PreviewWindow:
    """Aggregate per-campaign rows into one window's totals + top campaigns."""
    campaigns: list[PreviewCampaign] = []
    spend = impressions = clicks = conversions = 0.0
    currency: str | None = None
    for row in rows:
        c_spend = _num(row.get(spend_key))
        c_impr = _int(row.get(impr_key))
        c_clicks = _int(row.get(clicks_key))
        c_conv = _num(row.get(conv_key))
        spend += c_spend
        impressions += c_impr
        clicks += c_clicks
        conversions += c_conv
        currency = currency or row.get("currency")
        if c_spend or c_impr or c_clicks or c_conv:
            campaigns.append(
                PreviewCampaign(
                    platform=row.get("platform") or "",
                    campaign_name=row.get("campaign_name") or "(unnamed)",
                    spend=c_spend,
                    impressions=c_impr,
                    clicks=c_clicks,
                    conversions=c_conv,
                )
            )
    top = tuple(sorted(campaigns, key=lambda c: c.spend, reverse=True)[:TOP_CAMPAIGNS])
    has_data = bool(spend or impressions or clicks or conversions)
    return PreviewWindow(
        window_days=window_days,
        has_data=has_data,
        spend=spend,
        impressions=int(impressions),
        clicks=int(clicks),
        conversions=conversions,
        currency=currency,
        top_campaigns=top,
    )


def build_preview(
    source: PreviewSource,
    *,
    workspace_id: str,
    account_ids: list[str],
    today: date | None = None,
) -> PreviewData | None:
    """Return a 7-day and 30-day preview for the selected accounts.

    Returns ``None`` when there are no accounts to preview. Reads a single
    parameterized query (conditional aggregation gives both windows at once),
    scoped to ``workspace_id`` and ``account_ids`` for tenant isolation.
    """
    ids = [a for a in dict.fromkeys(account_ids) if a]
    if not ids:
        return None

    today = today or date.today()
    long_start = today - timedelta(days=LONG_WINDOW_DAYS - 1)
    short_start = today - timedelta(days=SHORT_WINDOW_DAYS - 1)
    table = source.qualified_table(UNIFIED_TABLE)

    sql = f"""
        SELECT
          platform,
          campaign_name,
          ANY_VALUE(currency) AS currency,
          SUM(IF(date >= @short_start, spend, 0)) AS spend_short,
          SUM(IF(date >= @short_start, impressions, 0)) AS impressions_short,
          SUM(IF(date >= @short_start, clicks, 0)) AS clicks_short,
          SUM(IF(date >= @short_start, conversions, 0)) AS conversions_short,
          SUM(spend) AS spend_long,
          SUM(impressions) AS impressions_long,
          SUM(clicks) AS clicks_long,
          SUM(conversions) AS conversions_long
        FROM `{table}`
        WHERE workspace_id = @workspace_id
          AND account_id IN UNNEST(@account_ids)
          AND date BETWEEN @long_start AND @today
        GROUP BY platform, campaign_name
    """
    params = [
        bigquery.ScalarQueryParameter("workspace_id", "STRING", workspace_id),
        bigquery.ArrayQueryParameter("account_ids", "STRING", ids),
        bigquery.ScalarQueryParameter("today", "DATE", today.isoformat()),
        bigquery.ScalarQueryParameter("long_start", "DATE", long_start.isoformat()),
        bigquery.ScalarQueryParameter("short_start", "DATE", short_start.isoformat()),
    ]
    rows = source.query_rows(sql, query_parameters=params)

    short = _window_from_rows(
        rows,
        window_days=SHORT_WINDOW_DAYS,
        spend_key="spend_short",
        impr_key="impressions_short",
        clicks_key="clicks_short",
        conv_key="conversions_short",
    )
    long = _window_from_rows(
        rows,
        window_days=LONG_WINDOW_DAYS,
        spend_key="spend_long",
        impr_key="impressions_long",
        clicks_key="clicks_long",
        conv_key="conversions_long",
    )
    return PreviewData(short=short, long=long)
