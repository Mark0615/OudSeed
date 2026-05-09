"""Smoke tests for committed BigQuery SQL files."""

from pathlib import Path


def test_weekly_summary_sql_contains_required_outputs() -> None:
    """Weekly summary SQL exposes the metrics needed by reporting and AI."""
    sql = Path("sql/weekly_summary.sql").read_text(encoding="utf-8")

    required_terms = [
        "weekly_performance_summary",
        "DATE_TRUNC(date, WEEK(MONDAY))",
        "SAFE_DIVIDE(SUM(clicks), SUM(impressions)) AS ctr",
        "previous_week_spend",
        "clicks_wow",
        "spend_wow_rate",
        "roas_wow_rate",
    ]

    for term in required_terms:
        assert term in sql


def test_monthly_summary_sql_contains_required_outputs() -> None:
    """Monthly summary SQL exposes the metrics needed by reporting and AI."""
    sql = Path("sql/monthly_summary.sql").read_text(encoding="utf-8")

    required_terms = [
        "monthly_performance_summary",
        "DATE_TRUNC(date, MONTH)",
        "SAFE_DIVIDE(SUM(clicks), SUM(impressions)) AS ctr",
        "previous_month_spend",
        "clicks_mom",
        "spend_mom_rate",
        "roas_mom_rate",
    ]

    for term in required_terms:
        assert term in sql


def test_looker_views_include_weekly_campaign_view() -> None:
    """Looker Studio views include the weekly campaign reporting view."""
    sql = Path("sql/looker_studio_views.sql").read_text(encoding="utf-8")

    assert "vw_looker_ads_campaign_weekly" in sql
    assert "link_clicks_wow" in sql
    assert "weekly_performance_summary" in sql


def test_looker_views_include_monthly_campaign_view() -> None:
    """Looker Studio views include the monthly campaign reporting view."""
    sql = Path("sql/looker_studio_views.sql").read_text(encoding="utf-8")

    assert "vw_looker_ads_campaign_monthly" in sql
    assert "link_clicks_mom" in sql
    assert "monthly_performance_summary" in sql


def test_create_tables_includes_summary_marts() -> None:
    """Warehouse bootstrap SQL includes weekly and monthly summary tables."""
    sql = Path("sql/create_tables.sql").read_text(encoding="utf-8")

    assert "weekly_performance_summary" in sql
    assert "monthly_performance_summary" in sql
    assert "spend_wow_rate FLOAT64" in sql
    assert "spend_mom_rate FLOAT64" in sql
