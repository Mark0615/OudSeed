"""On-demand AI report send for a single workspace (the dashboard's test-send button).

This reuses the deployed report pipeline's discovery + generate + send loop
(:mod:`src.ai.send_account_reports`) so the on-demand email matches exactly what
the scheduled Cloud Run job would produce — only the trigger and the scoping (one
workspace, its onboarding report schedule) differ. The web layer just resolves
the saved schedule, builds the config from the durable store, and maps the
outcome to a friendly, secret-free status banner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from src.ai.report_schedules import find_report_schedule
from src.ai.send_account_reports import (
    _generate_and_send_account_group_reports,
    discover_account_report_groups,
)
from src.storage.config_export import export_workspace_to_config
from src.utils.config_loader import load_config_from_yaml
from src.utils.date_utils import get_scheduled_report_period_start

if TYPE_CHECKING:
    from src.ai.openai_client import OpenAITextClient
    from src.destinations.bigquery import BigQueryDestination
    from src.notifications.email_delivery import SMTPEmailSender


@dataclass(frozen=True)
class SendNowResult:
    """Outcome of an on-demand report send.

    ``status`` is one of:
    - ``"sent"``         every account group's report was emailed
    - ``"no_recipient"`` no enabled schedule with a recipient was found
    - ``"no_groups"``    no account data for the period (run a first sync first)
    - ``"failed"``       generation/send raised for at least one group
    """

    status: str
    group_count: int = 0
    detail: str = ""


def build_workspace_report_config(
    session: Session,
    workspace_id: str,
    *,
    bigquery_project: str,
    bigquery_dataset: str,
    encryption_key: str | None = None,
) -> dict[str, Any]:
    """Build a pipeline-valid config dict from the workspace's durable data."""
    exported = export_workspace_to_config(
        session,
        workspace_id,
        bigquery_project=bigquery_project,
        bigquery_dataset=bigquery_dataset,
        encryption_key=encryption_key,
    )
    return load_config_from_yaml(parsed_config=exported)


def send_workspace_reports_now(
    *,
    config: dict[str, Any],
    destination: BigQueryDestination,
    openai_client: OpenAITextClient,
    sender: SMTPEmailSender,
    schedule_id: str,
    limit: int = 50,
    max_output_tokens: int = 5000,
) -> SendNowResult:
    """Generate and email the workspace's report group(s) for one schedule, now.

    Returns a structured outcome instead of raising so the dashboard can show a
    friendly banner. The heavy generate + send work is delegated to the shared
    pipeline loop so the email matches the scheduled job's output.
    """
    try:
        schedule = find_report_schedule(config, schedule_id)
    except ValueError:
        # No schedule with this id in the exported config (e.g. never saved).
        schedule = None
    if schedule is None or not schedule.email_to:
        return SendNowResult("no_recipient")

    report_type = schedule.report_type
    timezone_name = schedule.timezone or config.get("defaults", {}).get(
        "timezone", "Asia/Taipei"
    )
    period_start_date = get_scheduled_report_period_start(
        report_type=report_type,
        delivery_day=schedule.delivery_day,
        timezone=timezone_name,
    )
    workspace_id = config["workspace_id"]
    client_id = schedule.client_id

    groups = discover_account_report_groups(
        destination=destination,
        report_type=report_type,
        workspace_id=workspace_id,
        client_id=client_id,
        period_start_date=period_start_date,
    )
    if not groups:
        return SendNowResult("no_groups")

    try:
        _generate_and_send_account_group_reports(
            groups=groups,
            destination=destination,
            openai_client=openai_client,
            sender=sender,
            report_type=report_type,
            workspace_id=workspace_id,
            client_id=client_id,
            period_start_date=period_start_date,
            limit=limit,
            max_output_tokens=max_output_tokens,
            report_depth=schedule.depth,
            recipient=schedule.email_to,
        )
    except Exception as exc:
        return SendNowResult("failed", len(groups), _short_reason(exc))
    return SendNowResult("sent", len(groups))


def _short_reason(exc: Exception) -> str:
    """A short, single-line, secret-free reason from a send failure."""
    return " ".join(str(exc).split())[:200]
