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
    """HTML email renders campaign table, totals, and strong tags."""
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
        report_text="1. **本月 Summary**\n- **重點**：表現提升",
        account_group_name="Miniware TW",
    )

    assert "<table" in html
    assert "Campaign A" in html
    assert "$12,324" in html
    assert "$2.54" in html
    assert "4,850" in html
    assert "總計" in html
    assert "<strong>本月 Summary</strong>" in html
    assert "**" not in html
