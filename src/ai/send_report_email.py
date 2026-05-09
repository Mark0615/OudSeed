"""CLI entry point for emailing generated AI reports."""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from google.cloud import bigquery

from src.destinations.bigquery import BigQueryDestination
from src.notifications.email_delivery import SMTPEmailSender, load_smtp_email_config_from_env
from src.utils.config_loader import load_config, load_config_from_yaml


DEFAULT_CONFIG_PATH = "config/clients.yaml"


def main() -> None:
    """Send a generated AI report by email."""
    load_dotenv()
    config = _load_runtime_config()
    destination = _destination_from_config(config)
    recipient = _required_env("AI_REPORT_EMAIL_TO")

    report = fetch_report_for_email(
        destination=destination,
        report_id=os.getenv("AI_REPORT_ID"),
        report_type=os.getenv("AI_REPORT_TYPE"),
        period_start_date=os.getenv("AI_REPORT_PERIOD_START_DATE"),
        client_id=os.getenv("AI_REPORT_CLIENT_ID"),
    )
    subject = os.getenv("AI_REPORT_EMAIL_SUBJECT") or _default_subject(report)
    body = _format_email_body(report)

    sender = SMTPEmailSender(load_smtp_email_config_from_env())
    sender.send(recipient=recipient, subject=subject, body=body)
    print(
        "ai_report_email_sent="
        f"true report_id={report['report_id']} recipient={recipient}"
    )


def fetch_report_for_email(
    destination: BigQueryDestination,
    report_id: str | None = None,
    report_type: str | None = None,
    period_start_date: str | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
    """Fetch one successful report for email delivery."""
    filters = ["status = 'success'", "report_text IS NOT NULL"]
    parameters: list[bigquery.ScalarQueryParameter] = []

    if report_id:
        filters.append("report_id = @report_id")
        parameters.append(bigquery.ScalarQueryParameter("report_id", "STRING", report_id))
    if report_type:
        filters.append("report_type = @report_type")
        parameters.append(
            bigquery.ScalarQueryParameter("report_type", "STRING", report_type)
        )
    if period_start_date:
        filters.append("week_start_date = @period_start_date")
        parameters.append(
            bigquery.ScalarQueryParameter(
                "period_start_date",
                "DATE",
                period_start_date,
            )
        )
    if client_id:
        filters.append("client_id = @client_id")
        parameters.append(bigquery.ScalarQueryParameter("client_id", "STRING", client_id))

    table_id = destination._table_id("ai_report_logs")
    query = f"""
    SELECT
      report_id,
      workspace_id,
      client_id,
      report_type,
      week_start_date,
      week_end_date,
      report_text,
      model_name,
      created_at
    FROM `{table_id}`
    WHERE {" AND ".join(filters)}
    ORDER BY created_at DESC
    LIMIT 1
    """
    rows = destination.query_rows(query, query_parameters=parameters)
    if not rows:
        raise ValueError("No successful AI report matched the email filters.")

    return rows[0]


def _destination_from_config(config: dict[str, Any]) -> BigQueryDestination:
    bigquery_config = config.get("bigquery", {})
    project_id = os.getenv("GCP_PROJECT_ID") or bigquery_config.get("project_id")
    dataset_id = os.getenv("BIGQUERY_DATASET") or bigquery_config.get("dataset")
    if not project_id:
        raise ValueError("GCP project id is required via GCP_PROJECT_ID or config.bigquery.project_id.")
    if not dataset_id:
        raise ValueError("BigQuery dataset is required via BIGQUERY_DATASET or config.bigquery.dataset.")

    return BigQueryDestination(project_id=project_id, dataset_id=dataset_id)


def _load_runtime_config() -> dict[str, Any]:
    config_yaml = os.getenv("CLIENTS_CONFIG_YAML")
    if config_yaml:
        return load_config_from_yaml(config_yaml, source="CLIENTS_CONFIG_YAML")

    return load_config(os.getenv("CLIENTS_CONFIG_PATH", DEFAULT_CONFIG_PATH))


def _default_subject(report: dict[str, Any]) -> str:
    report_type_label = "週報" if report["report_type"] == "weekly" else "月報"
    return f"OudSeed 廣告成效{report_type_label}｜{report['week_start_date']}"


def _format_email_body(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"OudSeed AI 廣告成效報告",
            f"Report ID: {report['report_id']}",
            f"Client: {report['client_id']}",
            f"Period: {report['week_start_date']} - {report.get('week_end_date')}",
            "",
            report["report_text"],
        ]
    )


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


if __name__ == "__main__":
    main()
