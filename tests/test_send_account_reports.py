"""Tests for account-grouped report emails."""

import pytest

from src.ai.report_schedules import ReportSchedule
from src.ai.send_account_reports import (
    _bool_env,
    _default_period_start,
    _filter_report_groups,
    _format_preflight_lines,
    _format_report_group_lines,
    _generate_and_send_account_group_reports,
    _limit_report_groups,
    _load_account_report_config,
    _optional_positive_int_env,
    _send_account_report_email,
    discover_account_report_groups,
    format_html_email,
)
from src.storage.crypto import generate_key
from src.storage.db import build_session_factory, create_all, create_db_engine, session_scope
from src.storage.repository import (
    bind_account,
    create_client,
    create_platform_connection,
    create_report_schedule,
    create_workspace,
    store_connection_token,
    upsert_user_by_google_sub,
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

    def insert_rows(self, table_name: str, rows: list[dict]) -> int:
        self.rows.extend(rows)
        return len(rows)


class FakeSender:
    """Fake email sender for delivery tests."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[dict] = []

    def send(self, recipient: str, subject: str, body: str, html_body: str | None = None) -> None:
        if self.error:
            raise self.error
        self.sent.append(
            {
                "recipient": recipient,
                "subject": subject,
                "body": body,
                "html_body": html_body,
            }
        )


class FakeOpenAIClient:
    """Fake OpenAI client for account-group processing tests."""

    model = "gpt-test"


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


def test_format_preflight_lines_hides_recipient_and_account_ids() -> None:
    """Preflight mode prints resolved settings without leaking sensitive values."""
    groups = [
        {
            "account_group_name": "Miniware TW",
            "account_ids": ["act_123"],
            "platforms": ["meta_ads"],
        }
    ]

    lines = _format_preflight_lines(
        groups=groups,
        report_type="monthly",
        period_start_date="2026-04-01",
        report_depth="standard",
        max_output_tokens=5000,
        openai_timeout_seconds=180,
        recipient="recipient@example.com",
    )
    output = "\n".join(lines)

    assert "account_report_preflight=true" in output
    assert "report_type=monthly" in output
    assert "period_start_date=2026-04-01" in output
    assert "group_count=1" in output
    assert "depth=standard" in output
    assert "max_output_tokens=5000" in output
    assert "openai_timeout_seconds=180" in output
    assert "recipient_configured=true" in output
    assert "recipient@example.com" not in output
    assert "act_123" not in output


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


def test_default_period_start_uses_schedule_delivery_day(monkeypatch) -> None:
    """Schedule-based sends derive the period from the configured delivery day."""
    calls = {}

    def fake_get_scheduled_report_period_start(report_type: str, delivery_day: object, timezone: str) -> str:
        calls["report_type"] = report_type
        calls["delivery_day"] = delivery_day
        calls["timezone"] = timezone
        return "2026-04-01"

    monkeypatch.setattr(
        "src.ai.send_account_reports.get_scheduled_report_period_start",
        fake_get_scheduled_report_period_start,
    )
    schedule = ReportSchedule(
        schedule_id="monthly_email_default",
        client_id="demo_client_001",
        report_type="monthly",
        delivery_day=10,
        timezone="Asia/Taipei",
        email_to="recipient@example.com",
    )

    assert (
        _default_period_start(
            report_type="monthly",
            timezone="Asia/Taipei",
            schedule=schedule,
        )
        == "2026-04-01"
    )
    assert calls == {
        "report_type": "monthly",
        "delivery_day": 10,
        "timezone": "Asia/Taipei",
    }


def test_load_account_report_config_uses_database_when_workspace_id_set(monkeypatch, tmp_path) -> None:
    """AI_REPORT_WORKSPACE_ID makes the durable ReportSchedule rows the config source."""
    engine = create_db_engine(f"sqlite:///{tmp_path / 'reports.db'}")
    create_all(engine)
    session_factory = build_session_factory(engine)
    key = generate_key()

    with session_scope(session_factory) as session:
        owner = upsert_user_by_google_sub(session, google_sub="g-1", email="o@example.com")
        workspace = create_workspace(session, name="Acme", owner=owner)
        client = create_client(session, workspace_id=workspace.id, client_key="acme_tw", name="Acme TW")
        meta = create_platform_connection(
            session,
            workspace_id=workspace.id,
            platform="meta_ads",
            external_account_id="act_123",
            account_name="Acme Meta",
        )
        store_connection_token(meta, secret="meta-token", key=key)
        bind_account(session, client=client, connection=meta)
        create_report_schedule(
            session,
            client_id=client.id,
            schedule_key="monthly_email_default",
            report_type="monthly",
            delivery_day="1",
            timezone="Asia/Taipei",
            depth="standard",
            email_to="buyer@example.com",
            key=key,
        )
        workspace_id = workspace.id

    monkeypatch.setenv("AI_REPORT_WORKSPACE_ID", workspace_id)
    monkeypatch.setenv("GCP_PROJECT_ID", "oudseed")
    monkeypatch.setenv("BIGQUERY_DATASET", "ads_pipeline")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr("src.ai.send_account_reports.create_db_engine", lambda: engine)

    config = _load_account_report_config()

    assert config["workspace_id"] == workspace_id
    assert config["clients"][0]["client_id"] == "acme_tw"
    assert config["clients"][0]["report_schedules"][0]["schedule_id"] == "monthly_email_default"
    assert config["clients"][0]["report_schedules"][0]["email_to"] == "buyer@example.com"


def test_load_account_report_config_falls_back_to_yaml_without_workspace_id(monkeypatch) -> None:
    """Without AI_REPORT_WORKSPACE_ID, the legacy YAML/Secret Manager config still loads."""
    monkeypatch.delenv("AI_REPORT_WORKSPACE_ID", raising=False)
    monkeypatch.setattr(
        "src.ai.send_account_reports._load_runtime_config",
        lambda: {"workspace_id": "from_yaml", "clients": []},
    )

    assert _load_account_report_config() == {"workspace_id": "from_yaml", "clients": []}


def test_send_account_report_email_logs_delivery_failure() -> None:
    """SMTP failures write a failed delivery log row before bubbling up."""
    destination = FakeDestination(rows=[])
    sender = FakeSender(error=RuntimeError("smtp error"))

    with pytest.raises(RuntimeError, match="smtp error"):
        _send_account_report_email(
            sender=sender,
            destination=destination,
            report_id="report-1",
            workspace_id="mark_internal",
            client_id="demo_client_001",
            report_type="monthly",
            context={
                "period_start_date": "2026-04-01",
                "period_end_date": "2026-04-30",
            },
            report_text="AI report text",
            model_name="gpt-test",
            recipient="recipient@example.com",
            subject="Report",
            body="Plain body",
            html_body="<strong>HTML body</strong>",
        )

    assert destination.rows[0]["status"] == "failed"
    assert destination.rows[0]["report_id"] == "report-1"
    assert destination.rows[0]["error_message"] == "email_delivery_failed: smtp error"


def test_generate_and_send_account_group_reports_continues_after_group_failure(
    monkeypatch,
    capsys,
) -> None:
    """One failed account group does not block later groups."""
    calls: list[str] = []
    sent_report_ids: list[str] = []

    def fake_generate_and_log_report(**kwargs):
        account_id = kwargs["account_ids"][0]
        calls.append(account_id)
        if account_id == "2":
            raise RuntimeError("model error")
        return {
            "report_id": f"report-{account_id}",
            "report_text": "AI report text",
            "context": {
                "period_start_date": "2026-04-01",
                "period_end_date": "2026-04-30",
                "campaigns": [],
            },
        }

    def fake_send_account_report_email(**kwargs) -> None:
        sent_report_ids.append(kwargs["report_id"])

    monkeypatch.setattr(
        "src.ai.send_account_reports.generate_and_log_report",
        fake_generate_and_log_report,
    )
    monkeypatch.setattr(
        "src.ai.send_account_reports._send_account_report_email",
        fake_send_account_report_email,
    )

    with pytest.raises(RuntimeError, match="1 account group"):
        _generate_and_send_account_group_reports(
            groups=[
                {"account_group_name": "A", "account_ids": ["1"]},
                {"account_group_name": "B", "account_ids": ["2"]},
                {"account_group_name": "C", "account_ids": ["3"]},
            ],
            destination=FakeDestination(rows=[]),
            openai_client=FakeOpenAIClient(),
            sender=FakeSender(),
            report_type="monthly",
            workspace_id="mark_internal",
            client_id="demo_client_001",
            period_start_date="2026-04-01",
            limit=10,
            max_output_tokens=5000,
            report_depth="standard",
            recipient="recipient@example.com",
        )

    assert calls == ["1", "2", "3"]
    assert sent_report_ids == ["report-1", "report-3"]
    output = capsys.readouterr().out
    assert "account_report_email_sent=true report_id=report-1 account_group=A" in output
    assert "account_report_email_failed=true account_group=B error_type=RuntimeError" in output
    assert "account_report_email_sent=true report_id=report-3 account_group=C" in output
    assert "recipient=recipient@example.com" not in output
    assert "recipient_configured=true" in output
    assert "account_report_batch_finished=false group_count=3 sent_count=2 failed_count=1" in output


def test_generate_and_send_account_group_reports_logs_success_batch_summary(
    monkeypatch,
    capsys,
) -> None:
    """Successful account-group batches emit a compact operational summary."""

    def fake_generate_and_log_report(**kwargs):
        account_id = kwargs["account_ids"][0]
        return {
            "report_id": f"report-{account_id}",
            "report_text": "AI report text",
            "context": {
                "period_start_date": "2026-04-01",
                "period_end_date": "2026-04-30",
                "campaigns": [],
            },
        }

    monkeypatch.setattr(
        "src.ai.send_account_reports.generate_and_log_report",
        fake_generate_and_log_report,
    )

    _generate_and_send_account_group_reports(
        groups=[
            {"account_group_name": "A", "account_ids": ["1"]},
            {"account_group_name": "B", "account_ids": ["2"]},
        ],
        destination=FakeDestination(rows=[]),
        openai_client=FakeOpenAIClient(),
        sender=FakeSender(),
        report_type="monthly",
        workspace_id="mark_internal",
        client_id="demo_client_001",
        period_start_date="2026-04-01",
        limit=10,
        max_output_tokens=5000,
        report_depth="standard",
        recipient="recipient@example.com",
    )

    output = capsys.readouterr().out
    assert "account_report_batch_finished=true group_count=2 sent_count=2 failed_count=0" in output
    assert "recipient=recipient@example.com" not in output


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
