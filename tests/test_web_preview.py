"""Tests for the onboarding data preview (BigQuery read + rendering).

A fake source stands in for BigQueryDestination, so these run offline with no
GCP credentials.
"""

from __future__ import annotations

from src.web.preview import (
    PreviewCampaign,
    PreviewData,
    PreviewWindow,
    build_preview,
)
from src.web.views import _preview_section


class FakeSource:
    """Stands in for BigQueryDestination: records the query and returns rows."""

    def __init__(self, rows):
        self._rows = rows
        self.last_sql = None
        self.last_params = None

    def qualified_table(self, table_name: str) -> str:
        return f"proj.ds.{table_name}"

    def query_rows(self, sql, query_parameters=None):
        self.last_sql = sql
        self.last_params = query_parameters
        return self._rows


_ROWS = [
    {
        "platform": "meta_ads",
        "campaign_name": "Brand A",
        "currency": "USD",
        "spend_short": 100.0,
        "impressions_short": 1000,
        "clicks_short": 50,
        "conversions_short": 5.0,
        "spend_long": 400.0,
        "impressions_long": 4000,
        "clicks_long": 200,
        "conversions_long": 20.0,
    },
    {
        "platform": "google_ads",
        "campaign_name": "Search B",
        "currency": "USD",
        "spend_short": 250.0,
        "impressions_short": 500,
        "clicks_short": 80,
        "conversions_short": 8.0,
        "spend_long": 900.0,
        "impressions_long": 2000,
        "clicks_long": 300,
        "conversions_long": 33.0,
    },
]


def test_build_preview_returns_none_without_accounts():
    assert build_preview(FakeSource([]), workspace_id="w1", account_ids=[]) is None


def test_build_preview_aggregates_both_windows_and_ranks_campaigns():
    source = FakeSource(_ROWS)
    data = build_preview(source, workspace_id="w1", account_ids=["act_1", "act_2"])
    assert isinstance(data, PreviewData)
    assert data.has_data is True

    # 7-day window totals.
    assert data.short.window_days == 7
    assert data.short.spend == 350.0
    assert data.short.impressions == 1500
    assert data.short.clicks == 130
    assert data.short.conversions == 13.0
    # Top campaign ranked by spend within the window.
    assert data.short.top_campaigns[0].campaign_name == "Search B"

    # 30-day window totals.
    assert data.long.window_days == 30
    assert data.long.spend == 1300.0
    assert data.long.impressions == 6000
    assert data.long.top_campaigns[0].campaign_name == "Search B"

    # Query is tenant-scoped and parameterized (not string-interpolated ids).
    assert "workspace_id = @workspace_id" in source.last_sql
    assert "account_id IN UNNEST(@account_ids)" in source.last_sql
    param_names = {p.name for p in source.last_params}
    assert {"workspace_id", "account_ids", "today", "long_start", "short_start"} <= param_names


def test_build_preview_empty_rows_has_no_data():
    data = build_preview(FakeSource([]), workspace_id="w1", account_ids=["act_1"])
    assert data is not None
    assert data.has_data is False
    assert data.short.spend == 0.0 and data.long.spend == 0.0


def test_build_preview_dedupes_and_drops_blank_account_ids():
    source = FakeSource(_ROWS)
    build_preview(source, workspace_id="w1", account_ids=["act_1", "act_1", ""])
    ids_param = next(p for p in source.last_params if p.name == "account_ids")
    assert list(ids_param.values) == ["act_1"]


def test_preview_section_renders_real_numbers():
    data = PreviewData(
        short=PreviewWindow(
            window_days=7,
            has_data=True,
            spend=350.0,
            impressions=1500,
            clicks=130,
            conversions=13.0,
            currency="USD",
            top_campaigns=(PreviewCampaign("meta_ads", "Brand A", 100.0, 1000, 50, 5.0),),
        ),
        long=PreviewWindow(window_days=30, has_data=True, spend=1300.0, impressions=6000),
    )
    html = _preview_section(data)
    assert "$350" in html  # spend tile, money formatted
    assert "1,500" in html  # impressions, thousands separator
    assert "Brand A" in html  # top campaign row
    assert "id='pv-7'" in html and "id='pv-30'" in html  # both windows present


def test_preview_section_empty_state_when_none():
    html = _preview_section(None)
    assert "first sync" in html
    assert "pv-7" not in html  # no data windows rendered
