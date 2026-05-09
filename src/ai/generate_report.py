"""CLI entry point for generating one AI performance report."""

from __future__ import annotations

import os

from dotenv import load_dotenv

from src.ai.openai_client import OpenAITextClient
from src.ai.report_context import ReportType
from src.ai.report_generator import generate_and_log_report
from src.destinations.bigquery import BigQueryDestination
from src.utils.config_loader import load_config, load_config_from_yaml
from src.utils.date_utils import get_default_report_period_start


DEFAULT_CONFIG_PATH = "config/clients.yaml"


def main() -> None:
    """Generate one AI report from environment configuration."""
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
    timezone_name = config.get("defaults", {}).get("timezone", "Asia/Taipei")
    period_start_date = os.getenv("AI_REPORT_PERIOD_START_DATE") or get_default_report_period_start(
        report_type=report_type,
        timezone=os.getenv("AI_REPORT_TIMEZONE", timezone_name),
    )
    client_id = os.getenv("AI_REPORT_CLIENT_ID") or _first_enabled_client_id(config)
    account_id = os.getenv("AI_REPORT_ACCOUNT_ID")
    limit = _positive_int_env("AI_REPORT_LIMIT", 10)
    max_output_tokens = _positive_int_env("OPENAI_MAX_OUTPUT_TOKENS", 1800)
    openai_timeout_seconds = _positive_int_env("OPENAI_TIMEOUT_SECONDS", 60)

    print(
        "starting_ai_report_generation="
        f"true report_type={report_type} client_id={client_id} "
        f"period_start_date={period_start_date} model={os.getenv('OPENAI_MODEL', 'gpt-5.4 mini')} "
        f"timeout_seconds={openai_timeout_seconds}"
    )

    destination = BigQueryDestination(project_id=project_id, dataset_id=dataset_id)
    openai_client = OpenAITextClient(
        api_key=_required_env("OPENAI_API_KEY"),
        model=os.getenv("OPENAI_MODEL", "gpt-5.4 mini"),
        reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "medium"),
        timeout_seconds=openai_timeout_seconds,
    )
    result = generate_and_log_report(
        destination=destination,
        openai_client=openai_client,
        report_type=report_type,
        workspace_id=config["workspace_id"],
        client_id=client_id,
        period_start_date=period_start_date,
        account_id=account_id,
        limit=limit,
        max_output_tokens=max_output_tokens,
    )
    print(f"ai_report_id={result['report_id']} status={result['status']}")


def _report_type(value: str) -> ReportType:
    if value not in {"weekly", "monthly"}:
        raise ValueError("AI_REPORT_TYPE must be 'weekly' or 'monthly'.")
    return value


def _load_runtime_config() -> dict:
    """Load config from Secret Manager env content or a local file path."""
    config_yaml = os.getenv("CLIENTS_CONFIG_YAML")
    if config_yaml:
        return load_config_from_yaml(config_yaml, source="CLIENTS_CONFIG_YAML")

    return load_config(os.getenv("CLIENTS_CONFIG_PATH", DEFAULT_CONFIG_PATH))


def _first_enabled_client_id(config: dict) -> str:
    for client in config["clients"]:
        if client.get("enabled", True):
            return client["client_id"]
    raise ValueError("No enabled client found in config.clients.")


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _positive_int_env(name: str, default: int) -> int:
    """Read a positive integer environment variable."""
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


if __name__ == "__main__":
    main()
