"""Generate AI reports and persist report logs."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from src.ai.openai_client import OpenAITextClient
from src.ai.report_context import ReportType
from src.ai.weekly_report import build_report_prompt
from src.destinations.bigquery import BigQueryDestination


AI_REPORT_LOGS_TABLE = "ai_report_logs"


def generate_and_log_report(
    destination: BigQueryDestination,
    openai_client: OpenAITextClient,
    report_type: ReportType,
    workspace_id: str,
    client_id: str,
    period_start_date: str,
    account_id: str | None = None,
    account_ids: list[str] | None = None,
    limit: int = 10,
    max_output_tokens: int = 1800,
    report_depth: str = "standard",
) -> dict[str, Any]:
    """Generate one AI report and write the result to ai_report_logs."""
    report_id = str(uuid.uuid4())
    prompt_result = build_report_prompt(
        destination=destination,
        report_type=report_type,
        workspace_id=workspace_id,
        client_id=client_id,
        period_start_date=period_start_date,
        account_id=account_id,
        account_ids=account_ids,
        limit=limit,
        report_depth=report_depth,
    )
    context = prompt_result["context"]
    prompt = prompt_result["prompt"]

    try:
        report_text, raw_response = openai_client.generate_text(
            prompt=prompt,
            max_output_tokens=max_output_tokens,
        )
        log_row = _build_report_log(
            report_id=report_id,
            workspace_id=workspace_id,
            client_id=client_id,
            report_type=report_type,
            context=context,
            prompt=prompt,
            model_name=openai_client.model,
            status="success",
            report_text=report_text,
            error_message=None,
            raw_response=raw_response,
        )
        destination.insert_rows(AI_REPORT_LOGS_TABLE, [log_row])
        return {
            "report_id": report_id,
            "status": "success",
            "report_text": report_text,
            "context": context,
        }
    except Exception as exc:
        log_row = _build_report_log(
            report_id=report_id,
            workspace_id=workspace_id,
            client_id=client_id,
            report_type=report_type,
            context=context,
            prompt=prompt,
            model_name=openai_client.model,
            status="failed",
            report_text=None,
            error_message=str(exc),
            raw_response=None,
        )
        destination.insert_rows(AI_REPORT_LOGS_TABLE, [log_row])
        raise


def _build_report_log(
    report_id: str,
    workspace_id: str,
    client_id: str,
    report_type: str,
    context: dict[str, Any],
    prompt: str,
    model_name: str,
    status: str,
    report_text: str | None,
    error_message: str | None,
    raw_response: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build one ai_report_logs row."""
    return {
        "report_id": report_id,
        "workspace_id": workspace_id,
        "client_id": client_id,
        "week_start_date": context["period_start_date"],
        "week_end_date": context.get("period_end_date"),
        "report_type": report_type,
        "prompt_payload": json.dumps(
            {
                "context": context,
                "prompt": prompt,
                "raw_response": raw_response,
            },
            ensure_ascii=False,
        ),
        "report_text": report_text,
        "model_name": model_name,
        "status": status,
        "error_message": error_message,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
