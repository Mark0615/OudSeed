"""Inspect AI report log completeness for scheduled account reports."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv
from google.cloud import bigquery

from src.ai.generate_report import (
    _first_enabled_client_id,
    _load_runtime_config,
    _report_type,
)
from src.ai.send_account_reports import discover_account_report_groups
from src.destinations.bigquery import BigQueryDestination
from src.utils.date_utils import get_default_report_period_start

EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def main() -> None:
    """Print a sanitized AI report log status summary."""
    load_dotenv()
    config = _load_runtime_config()
    bigquery_config = config.get("bigquery", {})
    project_id = os.getenv("GCP_PROJECT_ID") or bigquery_config.get("project_id")
    dataset_id = os.getenv("BIGQUERY_DATASET") or bigquery_config.get("dataset")
    if not project_id:
        raise ValueError("GCP project id is required via GCP_PROJECT_ID or config.bigquery.project_id.")
    if not dataset_id:
        raise ValueError("BigQuery dataset is required via BIGQUERY_DATASET or config.bigquery.dataset.")

    report_type = _report_type(os.getenv("AI_REPORT_TYPE", "monthly"))
    timezone_name = os.getenv("AI_REPORT_TIMEZONE") or config.get("defaults", {}).get("timezone", "Asia/Taipei")
    period_start_date = os.getenv("AI_REPORT_PERIOD_START_DATE") or get_default_report_period_start(
        report_type=report_type,
        timezone=timezone_name,
    )
    client_id = os.getenv("AI_REPORT_CLIENT_ID") or _first_enabled_client_id(config)
    limit = _positive_int_env("AI_REPORT_LOG_LIMIT", 20)
    created_after = os.getenv("AI_REPORT_LOG_CREATED_AFTER")
    show_rows = _bool_env("AI_REPORT_LOG_SHOW_ROWS", True)

    destination = BigQueryDestination(project_id=project_id, dataset_id=dataset_id)
    expected_groups = discover_account_report_groups(
        destination=destination,
        report_type=report_type,
        workspace_id=config["workspace_id"],
        client_id=client_id,
        period_start_date=period_start_date,
    )
    log_rows = fetch_report_log_rows(
        destination=destination,
        report_type=report_type,
        workspace_id=config["workspace_id"],
        client_id=client_id,
        period_start_date=period_start_date,
        limit=limit,
        created_after=created_after,
    )
    counts = _status_counts(expected_groups=expected_groups, log_rows=log_rows)
    for line in format_report_log_status_lines(
        expected_groups=expected_groups,
        log_rows=log_rows,
        report_type=report_type,
        period_start_date=period_start_date,
        created_after=created_after,
        show_rows=show_rows,
    ):
        print(line)
    if _bool_env("AI_REPORT_LOG_REQUIRE_COMPLETE", False) and _has_status_failure(counts):
        raise SystemExit(1)


def fetch_report_log_rows(
    destination: BigQueryDestination,
    report_type: str,
    workspace_id: str,
    client_id: str,
    period_start_date: str,
    limit: int,
    created_after: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch sanitized report-log fields needed for operational checks."""
    created_after_filter = ""
    query_parameters: list[bigquery.ScalarQueryParameter] = [
        bigquery.ScalarQueryParameter("report_type", "STRING", report_type),
        bigquery.ScalarQueryParameter("period_start_date", "DATE", period_start_date),
        bigquery.ScalarQueryParameter("workspace_id", "STRING", workspace_id),
        bigquery.ScalarQueryParameter("client_id", "STRING", client_id),
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
    ]
    if created_after:
        created_after_filter = "AND created_at >= @created_after"
        query_parameters.append(bigquery.ScalarQueryParameter("created_after", "TIMESTAMP", created_after))

    query = f"""
    SELECT
      report_id,
      report_type,
      week_start_date AS period_start_date,
      week_end_date AS period_end_date,
      status,
      error_message,
      model_name,
      created_at,
      LENGTH(report_text) AS report_text_chars,
      TO_JSON_STRING(prompt_payload) AS prompt_payload_json
    FROM `{destination._table_id("ai_report_logs")}`
    WHERE report_type = @report_type
      AND week_start_date = @period_start_date
      AND workspace_id = @workspace_id
      AND client_id = @client_id
      {created_after_filter}
    ORDER BY created_at DESC
    LIMIT @limit
    """
    return destination.query_rows(
        query,
        query_parameters=query_parameters,
    )


def format_report_log_status_lines(
    expected_groups: list[dict[str, Any]],
    log_rows: list[dict[str, Any]],
    report_type: str,
    period_start_date: str,
    created_after: str | None = None,
    show_rows: bool = True,
) -> list[str]:
    """Return safe, line-oriented report-log status output."""
    counts = _status_counts(expected_groups=expected_groups, log_rows=log_rows)
    successful_expected_groups = counts["successful_expected_groups"]
    success_log_count = counts["success_log_count"]
    failed_rows = counts["failed_rows"]
    delivery_failures = counts["delivery_failures"]
    unconfirmed_group_count = counts["unconfirmed_group_count"]
    latest_created_at = str(log_rows[0].get("created_at")) if log_rows else "-"

    lines = [
        "ai_report_log_status=true "
        f"report_type={report_type} period_start_date={period_start_date} "
        f"created_after={created_after or '-'} "
        f"expected_group_count={len(expected_groups)} "
        f"successful_group_count={len(successful_expected_groups)} "
        f"success_log_count={success_log_count} "
        f"failed_log_count={len(failed_rows)} "
        f"delivery_failure_count={len(delivery_failures)} "
        f"unconfirmed_group_count={unconfirmed_group_count} "
        f"latest_created_at={latest_created_at}"
    ]
    for index, group in enumerate(expected_groups, start=1):
        platforms = ",".join(str(platform) for platform in group.get("platforms", [])) or "-"
        lines.append(
            "expected_account_group="
            f"{index} name={group.get('account_group_name')} "
            f"platforms={platforms} "
            f"account_count={len(group.get('account_ids', []))}"
        )

    if show_rows:
        for index, row in enumerate(log_rows, start=1):
            account_group = _account_group_from_prompt_payload(row.get("prompt_payload_json"))
            line = (
                "ai_report_log="
                f"{index} report_id={row.get('report_id')} "
                f"status={row.get('status')} "
                f"account_group={account_group} "
                f"model={row.get('model_name') or '-'} "
                f"report_text_chars={row.get('report_text_chars') or 0} "
                f"created_at={row.get('created_at')}"
            )
            if row.get("error_message"):
                line += f" error={_sanitize_error(str(row['error_message']))}"
            lines.append(line)
    return lines


def _status_counts(
    expected_groups: list[dict[str, Any]],
    log_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return report-log completeness counters."""
    expected_group_names = {
        str(group.get("account_group_name"))
        for group in expected_groups
        if group.get("account_group_name")
    }
    successful_group_names = {
        _account_group_from_prompt_payload(row.get("prompt_payload_json"))
        for row in log_rows
        if row.get("status") == "success"
    }
    successful_group_names = {
        name for name in successful_group_names if name not in {"-", "multiple"}
    }
    successful_expected_groups = successful_group_names & expected_group_names
    success_log_count = sum(1 for row in log_rows if row.get("status") == "success")
    failed_rows = [row for row in log_rows if row.get("status") == "failed"]
    delivery_failures = [
        row
        for row in failed_rows
        if str(row.get("error_message") or "").startswith("email_delivery_failed:")
    ]
    unconfirmed_group_count = max(len(expected_group_names) - len(successful_expected_groups), 0)
    return {
        "successful_expected_groups": successful_expected_groups,
        "success_log_count": success_log_count,
        "failed_rows": failed_rows,
        "delivery_failures": delivery_failures,
        "unconfirmed_group_count": unconfirmed_group_count,
    }


def _has_status_failure(counts: dict[str, Any]) -> bool:
    return bool(
        counts["unconfirmed_group_count"]
        or counts["failed_rows"]
        or counts["delivery_failures"]
    )


def _account_group_from_prompt_payload(prompt_payload_json: object) -> str:
    payload = _load_payload(prompt_payload_json)
    context = payload.get("context") if isinstance(payload, dict) else None
    campaigns = context.get("campaigns") if isinstance(context, dict) else None
    if not isinstance(campaigns, list):
        return "-"

    names = [
        str(row.get("account_name")).strip()
        for row in campaigns
        if isinstance(row, dict) and row.get("account_name")
    ]
    unique_names = list(dict.fromkeys(name for name in names if name))
    if not unique_names:
        return "-"
    if len(unique_names) == 1:
        return _sanitize_output_value(unique_names[0])
    return "multiple"


def _load_payload(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _sanitize_error(value: str) -> str:
    sanitized = _sanitize_output_value(value)
    sanitized = re.sub(r"\s+", "_", sanitized)
    return sanitized[:180]


def _sanitize_output_value(value: str) -> str:
    return EMAIL_PATTERN.sub("[email]", value)


def _positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value in {None, ""}:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value in {None, ""}:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


if __name__ == "__main__":
    main()
