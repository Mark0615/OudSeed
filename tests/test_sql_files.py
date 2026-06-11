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
        "add_to_cart_wow",
        "purchase_wow",
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
        "add_to_cart_mom",
        "purchase_mom",
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
    assert "add_to_cart_wow" in sql
    assert "purchase_wow" in sql
    assert "weekly_performance_summary" in sql


def test_looker_views_include_monthly_campaign_view() -> None:
    """Looker Studio views include the monthly campaign reporting view."""
    sql = Path("sql/looker_studio_views.sql").read_text(encoding="utf-8")

    assert "vw_looker_ads_campaign_monthly" in sql
    assert "link_clicks_mom" in sql
    assert "add_to_cart_mom" in sql
    assert "purchase_mom" in sql
    assert "monthly_performance_summary" in sql


def test_looker_views_include_ai_report_logs_view() -> None:
    """Looker Studio views include generated AI report output."""
    sql = Path("sql/looker_studio_views.sql").read_text(encoding="utf-8")

    assert "vw_looker_ai_report_logs" in sql
    assert "ai_report_logs" in sql
    assert "account_group_name" in sql
    assert "is_email_delivery_failure" in sql
    assert "has_report_text" in sql
    assert "report_text_chars" in sql


def test_meta_wide_view_exposes_windsor_style_columns() -> None:
    """The wide Meta view flattens raw_payload into named Windsor-style columns."""
    sql = Path("sql/meta_ads_wide_view.sql").read_text(encoding="utf-8")

    # Built as a view over the raw JSON payload (not the unified/compact table).
    assert "vw_looker_meta_ads_wide" in sql
    assert "raw_meta_ads_daily" in sql
    assert "JSON_QUERY_ARRAY(r.raw_payload, '$.actions')" in sql

    # A representative spread of the flattened columns Data Studio will read.
    required_columns = [
        "AS spend",
        "AS impressions",
        "AS reach",
        "AS frequency",
        "AS link_clicks",
        "AS purchases",
        "AS purchases_value",
        "AS purchase_roas",
        "AS adds_to_cart",
        "AS checkouts_initiated",
        "AS leads",
        "AS landing_page_views",
        "AS thruplays",
        "AS video_watched_100",
    ]
    for column in required_columns:
        assert column in sql, f"missing wide-view column: {column}"


def test_google_wide_view_exposes_windsor_style_columns() -> None:
    """The wide Google view flattens raw_payload into named Windsor-style columns."""
    sql = Path("sql/google_ads_wide_view.sql").read_text(encoding="utf-8")

    # Built as a view over the raw Google JSON payload (not the unified table),
    # filtered to the ad grain so spend is not multiplied across breakdowns.
    assert "vw_looker_google_ads_wide" in sql
    assert "raw_google_ads_daily" in sql
    assert "r.report_level = 'ad'" in sql

    required_columns = [
        "AS spend",
        "AS impressions",
        "AS clicks",
        "AS conversions",
        "AS conversion_value",
        "AS ctr",
        "AS cpc",
        "AS cpm",
        "AS cpa",
        "AS campaign_name",
        "AS ad_group_name",
        "AS ad_name",
    ]
    for column in required_columns:
        assert column in sql, f"missing wide-view column: {column}"


def test_google_keyword_and_search_term_wide_views() -> None:
    """Keyword + search-term wide views flatten the already-collected raw rows."""
    kw = Path("sql/google_ads_keyword_wide_view.sql").read_text(encoding="utf-8")
    assert "vw_looker_google_ads_keyword_wide" in kw
    assert "r.report_level = 'keyword'" in kw
    for column in ("AS keyword_text", "AS keyword_match_type", "AS spend",
                   "AS conversions", "AS clicks"):
        assert column in kw, f"missing keyword-view column: {column}"

    st = Path("sql/google_ads_search_term_wide_view.sql").read_text(encoding="utf-8")
    assert "vw_looker_google_ads_search_term_wide" in st
    assert "r.report_level = 'search_term'" in st
    for column in ("AS search_term", "AS spend", "AS conversions", "AS clicks"):
        assert column in st, f"missing search-term-view column: {column}"


def test_meta_wide_view_is_wired_into_reporting_refresh() -> None:
    """The wide views are part of the refreshed reporting SQL so they stay current."""
    from src.main import SUMMARY_SQL_PATHS

    names = {p.name for p in SUMMARY_SQL_PATHS}
    assert "meta_ads_wide_view.sql" in names
    assert "google_ads_wide_view.sql" in names
    assert "google_ads_keyword_wide_view.sql" in names
    assert "google_ads_search_term_wide_view.sql" in names


def test_create_tables_includes_summary_marts() -> None:
    """Warehouse bootstrap SQL includes weekly and monthly summary tables."""
    sql = Path("sql/create_tables.sql").read_text(encoding="utf-8")

    assert "weekly_performance_summary" in sql
    assert "monthly_performance_summary" in sql
    assert "spend_wow_rate FLOAT64" in sql
    assert "spend_mom_rate FLOAT64" in sql
    assert "add_to_cart FLOAT64" in sql
    assert "post_engagement FLOAT64" in sql
