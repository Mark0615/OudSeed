"""Tests for AI report log operational status output."""

from __future__ import annotations

from src.ai.report_log_status import (
    _account_group_from_prompt_payload,
    format_report_log_status_lines,
)


def test_format_report_log_status_lines_summarizes_success_and_failures() -> None:
    """Operational status output compares expected groups with report logs."""
    expected_groups = [
        {
            "account_group_name": "JK貓舍",
            "account_ids": ["customer-1"],
            "platforms": ["google_ads"],
        },
        {
            "account_group_name": "Miniware TW",
            "account_ids": ["act_123"],
            "platforms": ["meta_ads"],
        },
    ]
    log_rows = [
        {
            "report_id": "report-2",
            "status": "failed",
            "error_message": "email_delivery_failed: SMTP rejected recipient@example.com",
            "model_name": "gpt-5.2",
            "report_text_chars": 2400,
            "created_at": "2026-05-29T01:02:00Z",
            "prompt_payload_json": '{"context":{"campaigns":[{"account_name":"Miniware TW"}]}}',
        },
        {
            "report_id": "report-1",
            "status": "success",
            "error_message": None,
            "model_name": "gpt-5.2",
            "report_text_chars": 3200,
            "created_at": "2026-05-29T01:01:00Z",
            "prompt_payload_json": '{"context":{"campaigns":[{"account_name":"JK貓舍"}]}}',
        },
    ]

    output = "\n".join(
        format_report_log_status_lines(
            expected_groups=expected_groups,
            log_rows=log_rows,
            report_type="monthly",
            period_start_date="2026-04-01",
            created_after="2026-05-28T13:52:00Z",
        )
    )

    assert "ai_report_log_status=true" in output
    assert "created_after=2026-05-28T13:52:00Z" in output
    assert "expected_group_count=2" in output
    assert "successful_group_count=1" in output
    assert "success_log_count=1" in output
    assert "failed_log_count=1" in output
    assert "delivery_failure_count=1" in output
    assert "unconfirmed_group_count=1" in output
    assert "expected_account_group=1 name=JK貓舍 platforms=google_ads account_count=1" in output
    assert "account_group=Miniware TW" in output
    assert "recipient@example.com" not in output
    assert "[email]" in output


def test_account_group_from_prompt_payload_handles_missing_or_multiple_names() -> None:
    """Account-group inference is conservative when context is incomplete."""
    assert _account_group_from_prompt_payload(None) == "-"
    assert _account_group_from_prompt_payload("{}") == "-"
    assert (
        _account_group_from_prompt_payload(
            '{"context":{"campaigns":[{"account_name":"A"},{"account_name":"B"}]}}'
    )
        == "multiple"
    )


def test_format_report_log_status_lines_can_hide_row_details() -> None:
    """Summary-only output keeps routine ops checks compact."""
    lines = format_report_log_status_lines(
        expected_groups=[
            {
                "account_group_name": "Miniware TW",
                "account_ids": ["act_123"],
                "platforms": ["meta_ads"],
            }
        ],
        log_rows=[
            {
                "report_id": "report-1",
                "status": "success",
                "error_message": None,
                "model_name": "gpt-5.2",
                "report_text_chars": 3200,
                "created_at": "2026-05-29T01:01:00Z",
                "prompt_payload_json": '{"context":{"campaigns":[{"account_name":"Miniware TW"}]}}',
            }
        ],
        report_type="monthly",
        period_start_date="2026-04-01",
        show_rows=False,
    )
    output = "\n".join(lines)

    assert "ai_report_log_status=true" in output
    assert "expected_account_group=1 name=Miniware TW" in output
    assert "ai_report_log=1" not in output
    assert "report-1" not in output
