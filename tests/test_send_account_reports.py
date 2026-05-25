"""Tests for account-grouped report emails."""

import pytest

from src.ai.send_account_reports import (
    _bool_env,
    _filter_report_groups,
    _format_report_group_lines,
    _limit_report_groups,
    _optional_positive_int_env,
    discover_account_report_groups,
    format_html_email,
)


class FakeDestination:
    """Fake destination for group discovery tests."""

    project_id = "oudseed"
    dataset_id = "ads_pipeline"

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.queries: list[str] = []

    def _table_id(self, table_name: str) -> str:
        return f"{self.project_id}.{self.dataset_id}.{table_name}"

    def query_rows(self, sql: str, query_parameters: list | None = None) -> list[dict]:
        self.queries.append(sql)
        return self.rows


def test_discover_account_report_groups_uses_account_name() -> None:
    """Account-name groups are returned for report delivery."""
    destination = FakeDestination(
        [
            {
                "account_group_name": "JK貓舍",
                "account_ids": ["1707085270"],
                "platforms": ["google_ads"],
            },
            {
                "account_group_name": "Miniware TW",
                "account_ids": ["act_123"],
                "platforms": ["meta_ads"],
            },
        ]
    )

    groups = discover_account_report_groups(
        destination=destination,
        report_type="monthly",
        workspace_id="mark_internal",
        client_id="demo_client_001",
        period_start_date="2026-04-01",
    )

    assert "vw_looker_ads_campaign_monthly" in destination.queries[0]
    assert [group["account_group_name"] for group in groups] == ["JK貓舍", "Miniware TW"]


def test_limit_report_groups_supports_one_off_test_sends() -> None:
    """Account-group sends can be capped for safe test emails."""
    groups = [
        {"account_group_name": "A", "account_ids": ["1"]},
        {"account_group_name": "B", "account_ids": ["2"]},
    ]

    assert _limit_report_groups(groups, None) == groups
    assert _limit_report_groups(groups, 1) == [groups[0]]


def test_filter_report_groups_matches_explicit_account_group_name() -> None:
    """Account-group sends can target one named group for test emails."""
    groups = [
        {"account_group_name": "JK貓舍", "account_ids": ["1"]},
        {"account_group_name": "Miniware TW", "account_ids": ["2"]},
    ]

    assert _filter_report_groups(groups, None) == groups
    assert _filter_report_groups(groups, "Miniware TW") == [groups[1]]

    with pytest.raises(ValueError, match="No account group matched"):
        _filter_report_groups(groups, "Missing Account")


def test_format_report_group_lines_hides_account_ids() -> None:
    """List mode prints group metadata without leaking real account ids."""
    groups = [
        {
            "account_group_name": "Miniware TW",
            "account_ids": ["act_123", "act_456"],
            "platforms": ["meta_ads"],
        }
    ]

    lines = _format_report_group_lines(
        groups=groups,
        report_type="monthly",
        period_start_date="2026-04-01",
    )
    output = "\n".join(lines)

    assert "account_report_groups=true" in output
    assert "group_count=1" in output
    assert "name=Miniware TW" in output
    assert "platforms=meta_ads" in output
    assert "account_count=2" in output
    assert "act_123" not in output
    assert "act_456" not in output


def test_optional_positive_int_env(monkeypatch) -> None:
    """Optional positive integer env helper supports unset test-send limits."""
    monkeypatch.delenv("AI_REPORT_ACCOUNT_GROUP_LIMIT", raising=False)
    assert _optional_positive_int_env("AI_REPORT_ACCOUNT_GROUP_LIMIT") is None

    monkeypatch.setenv("AI_REPORT_ACCOUNT_GROUP_LIMIT", "")
    assert _optional_positive_int_env("AI_REPORT_ACCOUNT_GROUP_LIMIT") is None

    monkeypatch.setenv("AI_REPORT_ACCOUNT_GROUP_LIMIT", "1")
    assert _optional_positive_int_env("AI_REPORT_ACCOUNT_GROUP_LIMIT") == 1

    monkeypatch.setenv("AI_REPORT_ACCOUNT_GROUP_LIMIT", "0")
    with pytest.raises(ValueError, match="positive integer"):
        _optional_positive_int_env("AI_REPORT_ACCOUNT_GROUP_LIMIT")


def test_bool_env(monkeypatch) -> None:
    """Boolean env helper accepts common true/false values."""
    monkeypatch.delenv("AI_REPORT_LIST_ACCOUNT_GROUPS", raising=False)
    assert _bool_env("AI_REPORT_LIST_ACCOUNT_GROUPS") is False

    monkeypatch.setenv("AI_REPORT_LIST_ACCOUNT_GROUPS", "true")
    assert _bool_env("AI_REPORT_LIST_ACCOUNT_GROUPS") is True

    monkeypatch.setenv("AI_REPORT_LIST_ACCOUNT_GROUPS", "0")
    assert _bool_env("AI_REPORT_LIST_ACCOUNT_GROUPS") is False

    monkeypatch.setenv("AI_REPORT_LIST_ACCOUNT_GROUPS", "maybe")
    with pytest.raises(ValueError, match="boolean"):
        _bool_env("AI_REPORT_LIST_ACCOUNT_GROUPS")


def test_format_html_email_renders_table_and_bold_without_markdown_stars() -> None:
    """HTML email renders tables, totals, strong tags, and normalized numbers."""
    context = {
        "period_start_date": "2026-04-01",
        "period_end_date": "2026-04-30",
        "campaigns": [
            {
                "platform": "meta_ads",
                "campaign_name": "Campaign A",
                "spend": 12324,
                "link_clicks": 4850,
                "impressions": 100000,
                "cpc": 2.541,
                "cpm": 123.24,
                "add_to_cart": 12,
                "cost_per_add_to_cart": 1027,
                "purchase": 3,
                "cost_per_purchase": 4108,
                "purchase_value": 20000,
                "roas": 1.622,
            }
        ],
        "diagnostics": {
            "metric_changes": {
                "cpc": {
                    "current": 2.54,
                    "previous": 1.9,
                    "delta": 0.64,
                    "likely_cause": "spend_moved_more_than_link_clicks",
                },
                "cpa": {
                    "current": 4108,
                    "previous": 3200,
                    "delta": 908,
                    "likely_cause": "spend_increased_while_conversions_did_not",
                },
                "roas": {
                    "current": 1.62,
                    "previous": 2.4,
                    "delta": -0.78,
                    "likely_cause": "spend_moved_more_than_conversion_value",
                },
            },
            "anomalies": [
                {
                    "kind": "sharp_cpa_increase",
                    "platform": "meta_ads",
                    "campaign_name": "Campaign A",
                    "spend": 12324,
                    "conversions": 3,
                    "roas": 1.622,
                }
            ],
            "detail_contributions": {
                "ad_groups": [
                    {
                        "platform": "meta_ads",
                        "campaign_name": "Campaign A",
                        "ad_group_name": "Ad Set A",
                        "action_bias": "reduce_pause_or_exclude",
                        "spend": 8000,
                        "spend_share": 0.6491,
                        "conversions": 0,
                        "cpa": None,
                        "roas": 0,
                    }
                ],
                "ads": [],
                "keywords": [],
                "search_terms": [],
            },
            "campaign_contributions": {
                "weaker_campaigns": [],
                "stronger_campaigns": [],
            },
        },
    }

    html = format_html_email(
        report_id="report-1",
        client_id="demo_client_001",
        context=context,
        report_text=(
            "1. **本月 Summary**\n"
            "| 指標 | 本期 | 前期 | 變化 |\n"
            "| --- | ---: | ---: | ---: |\n"
            "| Spend | $15948 | $50731 | 下降 $34783 |\n"
            "| Clicks | 2973 | 4331 | 下降 1358 |\n"
            "⚠️ CPC 上升，需要檢查 search terms"
        ),
        account_group_name="Miniware TW",
    )

    assert html.count("<table") >= 2
    assert "max-width:760px" not in html
    assert "background:#f5f1e8" not in html
    assert "overflow-x:auto" in html
    assert "min-width:980px" in html
    assert "Campaign A" in html
    assert "$12,324" in html
    assert "$2.54" in html
    assert "4,850" in html
    assert "$15,948" in html
    assert "$50,731" in html
    assert "$34,783" in html
    assert "2,973" in html
    assert "1,358" in html
    assert "border-left:4px solid #f97316" in html
    assert "診斷重點" in html
    assert "花費變動幅度大於連結點擊，推動 CPC 變化" in html
    assert "spend_moved_more_than_link_clicks" not in html
    assert "高花費但零轉換" not in html
    assert "CPA 明顯上升" in html
    assert "廣告組合: Ad Set A" in html
    assert "高花費低回收，建議降預算、暫停或排除" in html
    assert "reduce_pause_or_exclude" not in html
    assert "可能原因" in html
    assert "花費占比" in html
    assert "64.91%" in html
    assert "總計" in html
    assert "<strong>本月 Summary</strong>" in html
    assert "**" not in html


def test_format_html_email_renders_heading_hierarchy_without_oversized_actions() -> None:
    """HTML email respects Markdown heading levels and keeps action lines as prose."""
    html = format_html_email(
        report_id="report-1",
        client_id="demo_client_001",
        context={
            "period_start_date": "2026-04-01",
            "period_end_date": "2026-04-30",
            "campaigns": [],
        },
        report_text=(
            "# 2. 表現較好的廣告\n"
            "## 最佳主力活動：`需求字/Sale/Search`\n"
            "### 活動層級\n"
            "1. 先把預算移到已驗證能帶回收的字詞。\n"
        ),
        account_group_name="JK貓舍",
    )

    assert "## 2. 表現較好的廣告" not in html
    assert "<h2" in html
    assert "<h3" in html
    assert "<h4" in html
    assert "需求字/Sale/Search" in html
    assert "先把預算移到已驗證能帶回收的字詞" in html
    assert "<h2" in html.split("1. 先把預算移到已驗證能帶回收的字詞", 1)[0]
    assert "<p style=" in html.split("1. 先把預算移到已驗證能帶回收的字詞", 1)[0]
