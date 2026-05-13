"""Tests for AI report generation and logging."""

import pytest

from src.ai.report_generator import AI_REPORT_LOGS_TABLE, generate_and_log_report


class FakeDestination:
    """Fake destination that supports report context queries and log inserts."""

    def __init__(self) -> None:
        self.project_id = "oudseed"
        self.dataset_id = "ads_pipeline"
        self.inserted_rows: list[dict] = []

    def _table_id(self, table_name: str) -> str:
        """Return a fake fully-qualified table id."""
        return f"{self.project_id}.{self.dataset_id}.{table_name}"

    def query_rows(self, sql: str, query_parameters: list | None = None) -> list[dict]:
        """Return one fake context row."""
        return [
            {
                "period_start_date": "2025-03-01",
                "period_end_date": "2025-03-31",
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
                "total_impressions": 1000,
                "total_link_clicks": 100,
                "total_spend": 1200.0,
                "total_conversions": 6.0,
                "total_conversion_value": 3600.0,
            }
        ]

    def insert_rows(self, table_name: str, rows: list[dict]) -> int:
        """Record inserted rows."""
        assert table_name == AI_REPORT_LOGS_TABLE
        self.inserted_rows.extend(rows)
        return len(rows)


class FakeOpenAIClient:
    """Fake OpenAI client for report generator tests."""

    model = "gpt-test"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def generate_text(self, prompt: str, max_output_tokens: int = 1800) -> tuple[str, dict]:
        """Return fake report text or raise a fake error."""
        if self.error:
            raise self.error
        return "AI report text", {"output_text": "AI report text"}


def test_generate_and_log_report_writes_success_log() -> None:
    """Successful AI reports are logged."""
    destination = FakeDestination()
    openai_client = FakeOpenAIClient()

    result = generate_and_log_report(
        destination=destination,
        openai_client=openai_client,
        report_type="monthly",
        workspace_id="mark_internal",
        client_id="demo_client_001",
        period_start_date="2025-03-01",
        report_depth="deep",
    )

    assert result["status"] == "success"
    assert result["report_text"] == "AI report text"
    log_row = destination.inserted_rows[0]
    assert log_row["status"] == "success"
    assert log_row["report_type"] == "monthly"
    assert log_row["week_start_date"] == "2025-03-01"
    assert log_row["week_end_date"] == "2025-03-31"
    assert log_row["report_text"] == "AI report text"
    assert log_row["model_name"] == "gpt-test"
    assert "Prospecting" in log_row["prompt_payload"]
    assert '"report_depth": "deep"' in log_row["prompt_payload"]
    assert "Report depth: deep" in log_row["prompt_payload"]


def test_generate_and_log_report_writes_failed_log() -> None:
    """Failed AI calls are logged before the error is raised."""
    destination = FakeDestination()
    openai_client = FakeOpenAIClient(error=RuntimeError("model error"))

    with pytest.raises(RuntimeError, match="model error"):
        generate_and_log_report(
            destination=destination,
            openai_client=openai_client,
            report_type="monthly",
            workspace_id="mark_internal",
            client_id="demo_client_001",
            period_start_date="2025-03-01",
        )

    log_row = destination.inserted_rows[0]
    assert log_row["status"] == "failed"
    assert log_row["error_message"] == "model error"
    assert log_row["report_text"] is None
