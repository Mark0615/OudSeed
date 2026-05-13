"""Build weekly and monthly report prompts from BigQuery marts."""

from __future__ import annotations

from typing import Any

from src.ai.prompt_templates import render_performance_report_prompt
from src.ai.report_context import ReportType, build_report_context
from src.destinations.bigquery import BigQueryDestination


def build_report_prompt(
    destination: BigQueryDestination,
    report_type: ReportType,
    workspace_id: str,
    client_id: str,
    period_start_date: str,
    account_id: str | None = None,
    account_ids: list[str] | None = None,
    limit: int = 10,
    report_depth: str = "standard",
) -> dict[str, Any]:
    """Build report context plus a ready-to-send LLM prompt."""
    context = build_report_context(
        destination=destination,
        report_type=report_type,
        workspace_id=workspace_id,
        client_id=client_id,
        period_start_date=period_start_date,
        account_id=account_id,
        account_ids=account_ids,
        limit=limit,
    )
    context["report_depth"] = report_depth
    return {
        "context": context,
        "prompt": render_performance_report_prompt(context),
    }
