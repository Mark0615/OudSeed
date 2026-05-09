"""Tests for emailing generated AI reports."""

from datetime import date

from src.ai.send_report_email import _default_subject, _format_email_body, fetch_report_for_email


class FakeDestination:
    """Fake BigQuery destination for report email tests."""

    project_id = "oudseed"
    dataset_id = "ads_pipeline"

    def __init__(self) -> None:
        self.query: str | None = None
        self.parameters: list = []

    def _table_id(self, table_name: str) -> str:
        return f"{self.project_id}.{self.dataset_id}.{table_name}"

    def query_rows(self, sql: str, query_parameters: list | None = None) -> list[dict]:
        self.query = sql
        self.parameters = query_parameters or []
        return [
            {
                "report_id": "report_001",
                "workspace_id": "mark_internal",
                "client_id": "demo_client_001",
                "report_type": "weekly",
                "week_start_date": date(2026, 5, 4),
                "week_end_date": date(2026, 5, 10),
                "report_text": "Report body",
                "model_name": "gpt-5.2",
                "created_at": "2026-05-10T00:00:00Z",
            }
        ]


def test_fetch_report_for_email_filters_successful_reports() -> None:
    """Email report lookup filters to one successful report."""
    destination = FakeDestination()

    report = fetch_report_for_email(
        destination=destination,
        report_type="weekly",
        period_start_date="2026-05-04",
        client_id="demo_client_001",
    )

    assert report["report_id"] == "report_001"
    assert "status = 'success'" in destination.query
    assert "week_start_date = @period_start_date" in destination.query
    parameter_names = [parameter.name for parameter in destination.parameters]
    assert parameter_names == ["report_type", "period_start_date", "client_id"]


def test_email_subject_and_body_include_report_context() -> None:
    """Email subject/body include enough context for recipients."""
    report = {
        "report_id": "report_001",
        "client_id": "demo_client_001",
        "report_type": "weekly",
        "week_start_date": "2026-05-04",
        "week_end_date": "2026-05-10",
        "report_text": "Report body",
    }

    assert _default_subject(report) == "OudSeed 廣告成效週報｜2026-05-04"
    body = _format_email_body(report)
    assert "Report ID: report_001" in body
    assert "Report body" in body
