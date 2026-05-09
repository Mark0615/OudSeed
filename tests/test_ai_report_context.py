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
            "spend_delta": 200.0,
            "link_clicks_delta": 20,
            "spend_delta_rate": 0.2,
            "link_clicks_delta_rate": 0.25,
            "total_impressions": 1500,
            "total_link_clicks": 150,
            "total_spend": 1500.0,
            "total_conversions": 9.0,
            "total_conversion_value": 4800.0,
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
            "spend_delta": -100.0,
            "link_clicks_delta": 10,
            "spend_delta_rate": -0.25,
            "link_clicks_delta_rate": 0.25,
            "total_impressions": 1500,
            "total_link_clicks": 150,
            "total_spend": 1500.0,
            "total_conversions": 9.0,
            "total_conversion_value": 4800.0,
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


def test_render_performance_report_prompt_includes_context() -> None:
    """Prompt template includes instructions and the context JSON."""
    context = {
        "report_type": "weekly",
        "comparison": "week_over_week",
        "client_id": "demo_client_001",
        "campaigns": [{"campaign_name": "Prospecting", "spend": 1200.0}],
    }

    prompt = render_performance_report_prompt(context)

    assert "Traditional Chinese" in prompt
    assert "Do not invent numbers" in prompt
    assert "表現較好的廣告" in prompt
    assert "素材觀察" in prompt
    assert "Prospecting" in prompt


def test_build_report_prompt_returns_context_and_prompt() -> None:
    """Report prompt builder returns both machine context and LLM prompt text."""
    destination = FakeDestination(sample_weekly_rows())

    result = build_report_prompt(
        destination=destination,
        report_type="weekly",
        workspace_id="mark_internal",
        client_id="demo_client_001",
        period_start_date="2025-03-24",
    )

    assert result["context"]["totals"]["spend"] == 1500.0
    assert "Prospecting" in result["prompt"]
