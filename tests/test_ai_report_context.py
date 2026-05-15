"""Tests for AI report context builders."""

from datetime import date

import pytest

from src.ai.prompt_templates import render_performance_report_prompt
from src.ai.report_context import build_report_context
from src.ai.weekly_report import build_report_prompt


class FakeDestination:
    """Fake BigQuery destination for AI context tests."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.queries: list[str] = []
        self.parameters: list[list] = []
        self.project_id = "oudseed"
        self.dataset_id = "ads_pipeline"

    def _table_id(self, table_name: str) -> str:
        """Return a fake fully-qualified table id."""
        return f"{self.project_id}.{self.dataset_id}.{table_name}"

    def query_rows(self, sql: str, query_parameters: list | None = None) -> list[dict]:
        """Record query calls and return fake rows."""
        self.queries.append(sql)
        self.parameters.append(query_parameters or [])
        return self.rows


class QueueDestination(FakeDestination):
    """Fake destination that returns one queued result per query."""

    def __init__(self, query_results: list[list[dict]]) -> None:
        super().__init__(rows=[])
        self.query_results = query_results

    def query_rows(self, sql: str, query_parameters: list | None = None) -> list[dict]:
        self.queries.append(sql)
        self.parameters.append(query_parameters or [])
        return self.query_results.pop(0)


def sample_weekly_rows() -> list[dict]:
    """Return fake weekly campaign rows."""
    return [
        {
            "period_start_date": date(2025, 3, 24),
            "period_end_date": date(2025, 3, 30),
            "platform": "meta_ads",
            "account_id": "act_000000000000000",
            "account_name": "Demo Account",
            "campaign_id": "campaign_001",
            "campaign_name": "Prospecting",
            "impressions": 1000,
            "link_clicks": 100,
            "spend": 1200.0,
            "conversions": 6.0,
            "conversion_value": 3600.0,
            "ctr": 0.1,
            "cpc": 12.0,
            "cpm": 1200.0,
            "cpa": 200.0,
            "roas": 3.0,
            "previous_spend": 1000.0,
            "previous_link_clicks": 80,
            "previous_conversions": 8.0,
            "previous_cpc": 12.5,
            "previous_cpa": 125.0,
            "previous_roas": 4.2,
            "spend_delta": 200.0,
            "link_clicks_delta": 20,
            "conversions_delta": -2.0,
            "cpc_delta": -0.5,
            "cpa_delta": 75.0,
            "roas_delta": -1.2,
            "spend_delta_rate": 0.2,
            "link_clicks_delta_rate": 0.25,
            "conversions_delta_rate": -0.25,
            "cpc_delta_rate": -0.04,
            "cpa_delta_rate": 0.6,
            "roas_delta_rate": -0.2857142857,
            "total_impressions": 1500,
            "total_link_clicks": 150,
            "total_spend": 1500.0,
            "total_conversions": 9.0,
            "total_conversion_value": 4800.0,
            "total_previous_spend": 1400.0,
            "total_previous_link_clicks": 120,
            "total_previous_conversions": 10.0,
            "total_previous_add_to_cart": 0,
            "total_previous_purchase": 0,
        },
        {
            "period_start_date": date(2025, 3, 24),
            "period_end_date": date(2025, 3, 30),
            "platform": "meta_ads",
            "account_id": "act_000000000000000",
            "account_name": "Demo Account",
            "campaign_id": "campaign_002",
            "campaign_name": "Retargeting",
            "impressions": 500,
            "link_clicks": 50,
            "spend": 300.0,
            "conversions": 3.0,
            "conversion_value": 1200.0,
            "ctr": 0.1,
            "cpc": 6.0,
            "cpm": 600.0,
            "cpa": 100.0,
            "roas": 4.0,
            "previous_spend": 400.0,
            "previous_link_clicks": 40,
            "previous_conversions": 2.0,
            "previous_cpc": 10.0,
            "previous_cpa": 200.0,
            "previous_roas": 2.0,
            "spend_delta": -100.0,
            "link_clicks_delta": 10,
            "conversions_delta": 1.0,
            "cpc_delta": -4.0,
            "cpa_delta": -100.0,
            "roas_delta": 2.0,
            "spend_delta_rate": -0.25,
            "link_clicks_delta_rate": 0.25,
            "conversions_delta_rate": 0.5,
            "cpc_delta_rate": -0.4,
            "cpa_delta_rate": -0.5,
            "roas_delta_rate": 1.0,
            "total_impressions": 1500,
            "total_link_clicks": 150,
            "total_spend": 1500.0,
            "total_conversions": 9.0,
            "total_conversion_value": 4800.0,
            "total_previous_spend": 1400.0,
            "total_previous_link_clicks": 120,
            "total_previous_conversions": 10.0,
            "total_previous_add_to_cart": 0,
            "total_previous_purchase": 0,
        },
    ]


def test_build_weekly_report_context_queries_weekly_view() -> None:
    """Weekly context is built from the weekly Looker view."""
    destination = FakeDestination(sample_weekly_rows())

    context = build_report_context(
        destination=destination,
        report_type="weekly",
        workspace_id="mark_internal",
        client_id="demo_client_001",
        period_start_date="2025-03-24",
        account_id="act_000000000000000",
        limit=5,
    )

    assert "vw_looker_ads_campaign_weekly" in destination.queries[0]
    assert "account_id = @account_id" in destination.queries[0]
    assert context["report_type"] == "weekly"
    assert context["comparison"] == "week_over_week"
    assert context["period_end_date"] == "2025-03-30"
    assert context["totals"]["spend"] == 1500.0
    assert context["totals"]["link_clicks"] == 150
    assert context["totals"]["cpc"] == 10.0
    assert context["campaigns"][0]["campaign_name"] == "Prospecting"
    assert "metric_changes" in context["diagnostics"]
    assert (
        context["diagnostics"]["campaign_contributions"]["weaker_campaigns"][0][
            "campaign_name"
        ]
        == "Prospecting"
    )


def test_build_monthly_report_context_queries_monthly_view() -> None:
    """Monthly context is built from the monthly Looker view."""
    destination = FakeDestination([])

    context = build_report_context(
        destination=destination,
        report_type="monthly",
        workspace_id="mark_internal",
        client_id="demo_client_001",
        period_start_date="2025-03-01",
    )

    assert "vw_looker_ads_campaign_monthly" in destination.queries[0]
    assert "account_id = @account_id" not in destination.queries[0]
    assert context["comparison"] == "month_over_month"
    assert context["campaigns"] == []
    assert context["totals"]["spend"] == 0


def test_monthly_report_context_uses_complete_previous_period_totals() -> None:
    """Previous totals are fetched from the full previous month, not current campaigns only."""
    current_rows = [
        {
            "period_start_date": date(2026, 4, 1),
            "period_end_date": date(2026, 4, 30),
            "platform": "meta_ads",
            "account_id": "act_123",
            "account_name": "Miniware TW",
            "campaign_id": "campaign_001",
            "campaign_name": "Current Campaign",
            "impressions": 100,
            "link_clicks": 10,
            "spend": 100.0,
            "conversions": 2.0,
            "conversion_value": 300.0,
            "previous_spend": 20.0,
            "previous_link_clicks": 2,
            "previous_conversions": 1.0,
            "total_impressions": 100,
            "total_link_clicks": 10,
            "total_spend": 100.0,
            "total_conversions": 2.0,
            "total_conversion_value": 300.0,
            "total_previous_spend": 20.0,
            "total_previous_link_clicks": 2,
            "total_previous_conversions": 1.0,
        }
    ]
    previous_total_rows = [
        {
            "impressions": 1000,
            "link_clicks": 100,
            "spend": 500.0,
            "conversions": 8.0,
            "conversion_value": 900.0,
            "add_to_cart": 20.0,
            "purchase": 8.0,
            "purchase_value": 900.0,
        }
    ]
    destination = QueueDestination(
        [
            current_rows,
            previous_total_rows,
            [],
            [],
            [],
            [],
        ]
    )

    context = build_report_context(
        destination=destination,
        report_type="monthly",
        workspace_id="mark_internal",
        client_id="demo_client_001",
        period_start_date="2026-04-01",
        account_id="act_123",
    )

    assert context["totals"]["previous"]["spend"] == 500.0
    assert context["totals"]["previous"]["purchase"] == 8.0
    assert context["totals"]["delta"]["spend"] == -400.0
    assert context["totals"]["delta"]["purchase"] == -8.0
    assert "2026-03-01" in str(destination.parameters[1][0].value)


def test_build_report_context_rejects_invalid_limit() -> None:
    """Report context limits must be positive."""
    destination = FakeDestination([])

    with pytest.raises(ValueError, match="limit"):
        build_report_context(
            destination=destination,
            report_type="weekly",
            workspace_id="mark_internal",
            client_id="demo_client_001",
            period_start_date="2025-03-24",
            limit=0,
        )


def test_report_context_adds_detail_diagnostics() -> None:
    """Diagnostics annotate ad group, keyword, and search term contribution rows."""
    current_rows = [
        {
            "period_start_date": date(2026, 4, 1),
            "period_end_date": date(2026, 4, 30),
            "platform": "google_ads",
            "account_id": "google_123",
            "account_name": "Demo Google",
            "campaign_id": "campaign_001",
            "campaign_name": "Search Brand",
            "impressions": 1000,
            "link_clicks": 100,
            "spend": 1000.0,
            "conversions": 10.0,
            "conversion_value": 3000.0,
            "cpc": 10.0,
            "cpa": 100.0,
            "roas": 3.0,
            "previous_spend": 800.0,
            "previous_link_clicks": 100,
            "previous_conversions": 16.0,
            "previous_cpc": 8.0,
            "previous_cpa": 50.0,
            "previous_roas": 5.0,
            "cpc_delta_rate": 0.25,
            "cpa_delta_rate": 1.0,
            "roas_delta_rate": -0.4,
            "total_impressions": 1000,
            "total_link_clicks": 100,
            "total_spend": 1000.0,
            "total_conversions": 10.0,
            "total_conversion_value": 3000.0,
            "total_previous_spend": 800.0,
            "total_previous_link_clicks": 100,
            "total_previous_conversions": 16.0,
            "total_previous_add_to_cart": 0,
            "total_previous_purchase": 0,
        }
    ]
    previous_total_rows = [
        {
            "impressions": 1000,
            "link_clicks": 100,
            "spend": 800.0,
            "conversions": 16.0,
            "conversion_value": 4000.0,
            "add_to_cart": 0,
            "purchase": 0,
            "purchase_value": 0,
        }
    ]
    ad_group_rows = [
        {
            "platform": "google_ads",
            "account_id": "google_123",
            "campaign_id": "campaign_001",
            "campaign_name": "Search Brand",
            "ad_group_id": "adgroup_001",
            "ad_group_name": "Booking Terms",
            "spend": 700.0,
            "link_clicks": 70,
            "conversions": 0.0,
            "conversion_value": 0.0,
            "cpc": 10.0,
            "cpa": None,
            "roas": 0.0,
        }
    ]
    keyword_rows = [
        {
            "platform": "google_ads",
            "account_id": "google_123",
            "campaign_id": "campaign_001",
            "campaign_name": "Search Brand",
            "ad_group_id": "adgroup_001",
            "ad_group_name": "Booking Terms",
            "criterion_id": "kw_001",
            "keyword_text": "expensive booking",
            "keyword_match_type": "PHRASE",
            "spend": 400.0,
            "link_clicks": 40,
            "conversions": 0.0,
            "conversion_value": 0.0,
            "cpc": 10.0,
            "cpa": None,
            "roas": 0.0,
        }
    ]
    search_term_rows = [
        {
            "platform": "google_ads",
            "account_id": "google_123",
            "campaign_id": "campaign_001",
            "campaign_name": "Search Brand",
            "ad_group_id": "adgroup_001",
            "ad_group_name": "Booking Terms",
            "search_term": "free booking template",
            "spend": 300.0,
            "link_clicks": 30,
            "conversions": 0.0,
            "conversion_value": 0.0,
            "cpc": 10.0,
            "cpa": None,
            "roas": 0.0,
        }
    ]
    destination = QueueDestination(
        [
            current_rows,
            previous_total_rows,
            ad_group_rows,
            [],
            keyword_rows,
            search_term_rows,
        ]
    )

    context = build_report_context(
        destination=destination,
        report_type="monthly",
        workspace_id="mark_internal",
        client_id="demo_client_001",
        period_start_date="2026-04-01",
        account_id="google_123",
    )

    diagnostics = context["diagnostics"]
    assert diagnostics["detail_contributions"]["keywords"][0]["keyword_text"] == "expensive booking"
    assert (
        diagnostics["detail_contributions"]["search_terms"][0]["action_bias"]
        == "reduce_pause_or_exclude"
    )
    assert any(
        anomaly["kind"] == "high_spend_zero_conversions"
        for anomaly in diagnostics["anomalies"]
    )


def test_render_performance_report_prompt_includes_context() -> None:
    """Prompt template includes instructions and the context JSON."""
    context = {
        "report_type": "weekly",
        "comparison": "week_over_week",
        "report_depth": "deep",
        "client_id": "demo_client_001",
        "campaigns": [{"campaign_name": "Prospecting", "spend": 1200.0}],
    }

    prompt = render_performance_report_prompt(context)

    assert "Traditional Chinese" in prompt
    assert "Do not invent numbers" in prompt
    assert "表現較好的廣告" in prompt
    assert "素材觀察" in prompt
    assert "Prospecting" in prompt
    assert "thousands separators" in prompt
    assert "search terms" in prompt
    assert "Report depth: deep" in prompt
    assert "consultant-style" in prompt
    assert "diagnostics" in prompt


def test_build_report_prompt_returns_context_and_prompt() -> None:
    """Report prompt builder returns both machine context and LLM prompt text."""
    destination = FakeDestination(sample_weekly_rows())

    result = build_report_prompt(
        destination=destination,
        report_type="weekly",
        workspace_id="mark_internal",
        client_id="demo_client_001",
        period_start_date="2025-03-24",
        report_depth="brief",
    )

    assert result["context"]["totals"]["spend"] == 1500.0
    assert result["context"]["report_depth"] == "brief"
    assert "diagnostics" in result["context"]
    assert "Report depth: brief" in result["prompt"]
    assert "Prospecting" in result["prompt"]
