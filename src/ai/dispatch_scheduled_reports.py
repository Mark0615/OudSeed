"""Send the AI reports that are due today, across every workspace.

This is the automatic counterpart of the dashboard's "send a test report now"
button: run it once a day (e.g. from a Cloud Scheduler → Cloud Run Job) and it
emails each workspace whose report schedule falls due today, reusing the same
:mod:`src.ai.workspace_reports` pipeline so the output is identical.

Run locally:  ``python -m src.ai.dispatch_scheduled_reports``

Logs are secret-free and never include workspace/account identifiers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from src.ai.openai_client import OpenAITextClient
from src.ai.workspace_reports import (
    SendNowResult,
    build_workspace_report_config,
    send_workspace_reports_now,
)
from src.destinations.bigquery import BigQueryDestination
from src.notifications.email_delivery import (
    SMTPEmailSender,
    load_smtp_email_config_from_env,
)
from src.storage.db import build_session_factory, create_db_engine, session_scope
from src.storage.repository import list_all_workspaces, list_clients, list_report_schedules
from src.utils.date_utils import is_report_due_today


@dataclass(frozen=True)
class DueSchedule:
    """A workspace report schedule that is due to send today."""

    workspace_id: str
    schedule_key: str
    report_type: str


@dataclass(frozen=True)
class DispatchResult:
    """Outcome of dispatching one due schedule."""

    schedule_key: str
    status: str  # SendNowResult.status, or "error" when the send raised
    detail: str = ""


def find_due_schedules(session: Session, *, now: datetime | None = None) -> list[DueSchedule]:
    """Return every enabled, recipient-bearing schedule that is due today."""
    due: list[DueSchedule] = []
    for workspace in list_all_workspaces(session):
        for client in list_clients(session, workspace.id):
            for schedule in list_report_schedules(session, client.id):
                if not schedule.enabled or not schedule.encrypted_email_to:
                    continue
                if is_report_due_today(
                    schedule.report_type,
                    schedule.delivery_day,
                    schedule.timezone or "Asia/Taipei",
                    now=now,
                ):
                    due.append(
                        DueSchedule(
                            workspace_id=workspace.id,
                            schedule_key=schedule.schedule_key,
                            report_type=schedule.report_type,
                        )
                    )
    return due


def dispatch_due_reports(
    session: Session,
    *,
    destination: BigQueryDestination,
    openai_client: OpenAITextClient,
    sender: SMTPEmailSender,
    bigquery_project: str,
    bigquery_dataset: str,
    encryption_key: str | None = None,
    now: datetime | None = None,
    send=send_workspace_reports_now,
) -> list[DispatchResult]:
    """Send each due schedule's report, isolating per-schedule failures."""
    results: list[DispatchResult] = []
    for due in find_due_schedules(session, now=now):
        try:
            config = build_workspace_report_config(
                session,
                due.workspace_id,
                bigquery_project=bigquery_project,
                bigquery_dataset=bigquery_dataset,
                encryption_key=encryption_key,
            )
            outcome: SendNowResult = send(
                config=config,
                destination=destination,
                openai_client=openai_client,
                sender=sender,
                schedule_id=due.schedule_key,
            )
            results.append(DispatchResult(due.schedule_key, outcome.status, outcome.detail))
        except Exception as exc:
            # One workspace failing must not stop the rest.
            results.append(DispatchResult(due.schedule_key, "error", type(exc).__name__))
    return results


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def main() -> None:
    """Dispatch all reports due today using environment-configured services."""
    load_dotenv()
    project_id = _required_env("GCP_PROJECT_ID")
    dataset_id = _required_env("BIGQUERY_DATASET")

    destination = BigQueryDestination(project_id=project_id, dataset_id=dataset_id)
    openai_client = OpenAITextClient(
        api_key=_required_env("OPENAI_API_KEY"),
        model=os.getenv("OPENAI_MODEL", "gpt-5.2"),
        reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "medium"),
        timeout_seconds=_int_env("OPENAI_TIMEOUT_SECONDS", 120),
    )
    sender = SMTPEmailSender(load_smtp_email_config_from_env())

    engine = create_db_engine()
    session_factory = build_session_factory(engine)
    with session_scope(session_factory) as session:
        results = dispatch_due_reports(
            session,
            destination=destination,
            openai_client=openai_client,
            sender=sender,
            bigquery_project=project_id,
            bigquery_dataset=dataset_id,
            encryption_key=os.getenv("TOKEN_ENCRYPTION_KEY"),
        )

    sent = sum(1 for r in results if r.status == "sent")
    failed = sum(1 for r in results if r.status in {"failed", "error"})
    print(
        "scheduled_reports_dispatched=true "
        f"due={len(results)} sent={sent} failed={failed}"
    )
    for result in results:
        # Schedule key is non-sensitive; workspace/account ids are never logged.
        print(f"scheduled_report schedule={result.schedule_key} status={result.status}")


if __name__ == "__main__":
    main()
