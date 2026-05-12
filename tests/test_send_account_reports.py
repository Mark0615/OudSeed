"""Tests for account-grouped report emails."""

from src.ai.send_account_reports import discover_account_report_groups, format_html_email


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
