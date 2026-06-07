"""Export a workspace's durable data into the pipeline's ``clients.yaml`` shape.

This is the bridge that makes the durable store usable by the existing sync and
AI-report pipeline (`src/main.py`, `src/ai/...`), which consume the config dict
validated by :mod:`src.utils.config_loader`. Recipient emails are decrypted on
export (the resulting config may be written to the gitignored `config/clients.yaml`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.storage.models import Workspace
from src.storage.repository import (
    get_connection,
    list_client_accounts,
    list_clients,
    list_report_schedules,
    read_schedule_email_to,
)

# Pipeline defaults mirror config/clients.example.yaml.
DEFAULT_PIPELINE_DEFAULTS: dict[str, Any] = {
    "timezone": "Asia/Taipei",
    "sync_days_back": 7,
    "attribution_setting": "platform_default",
    "timezone_setting": "platform_account_default",
    "conversion_action_type": "purchase",
}


def export_workspace_to_config(
    session: Session,
    workspace_id: str,
    *,
    bigquery_project: str,
    bigquery_dataset: str,
    encryption_key: str | None = None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a pipeline-valid config dict from a workspace's durable data.

    Raises ValueError if the workspace does not exist. The returned dict matches
    what `src.utils.config_loader.load_config_from_yaml` validates.
    """
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise ValueError(f"Unknown workspace: {workspace_id!r}")

    merged_defaults = {**DEFAULT_PIPELINE_DEFAULTS, **(defaults or {})}
    bigquery = {"project_id": bigquery_project, "dataset": bigquery_dataset}

    clients_out: list[dict[str, Any]] = []
    for client in list_clients(session, workspace_id):
        meta_accounts: list[dict[str, Any]] = []
        google_accounts: list[dict[str, Any]] = []
        for binding in list_client_accounts(session, client.id):
            connection = get_connection(session, binding.platform_connection_id)
            if connection is None:
                continue
            # Only accounts the user selected for sync ("active") are enabled;
            # paused/pending/revoked accounts are exported disabled.
            enabled = connection.status == "active"
            if connection.platform == "meta_ads":
                meta_accounts.append(
                    {
                        "ad_account_id": connection.external_account_id,
                        "account_name": connection.account_name,
                        "report_level": "ad",
                        "enabled": enabled,
                    }
                )
            elif connection.platform == "google_ads":
                google_accounts.append(
                    {
                        "customer_id": connection.external_account_id,
                        "account_name": connection.account_name,
                        "login_customer_id": None,
                        "report_level": "ad",
                        "enabled": enabled,
                    }
                )

        platforms: dict[str, Any] = {}
        if meta_accounts:
            platforms["meta_ads"] = {"enabled": True, "accounts": meta_accounts}
        if google_accounts:
            platforms["google_ads"] = {"enabled": True, "accounts": google_accounts}

        client_out: dict[str, Any] = {
            "client_id": client.client_key,
            "client_name": client.name,
            "enabled": True,
            "platforms": platforms,
            "destinations": {
                "bigquery": {
                    "enabled": True,
                    "project_id": bigquery_project,
                    "dataset": bigquery_dataset,
                }
            },
        }

        schedules_out = _export_schedules(session, client.id, encryption_key)
        if schedules_out:
            client_out["report_schedules"] = schedules_out

        clients_out.append(client_out)

    return {
        "workspace_id": workspace_id,
        "defaults": merged_defaults,
        "bigquery": bigquery,
        "clients": clients_out,
    }


def _export_schedules(
    session: Session, client_id: str, encryption_key: str | None
) -> list[dict[str, Any]]:
    """Build the report_schedules list for a client."""
    schedules_out: list[dict[str, Any]] = []
    for schedule in list_report_schedules(session, client_id):
        entry: dict[str, Any] = {
            "schedule_id": schedule.schedule_key,
            "enabled": schedule.enabled,
            "report_type": schedule.report_type,
            "delivery_day": _coerce_delivery_day(schedule.report_type, schedule.delivery_day),
            "channel": schedule.channel,
            "depth": schedule.depth,
        }
        if schedule.timezone:
            entry["timezone"] = schedule.timezone
        email_to = read_schedule_email_to(schedule, key=encryption_key)
        if email_to:
            entry["email_to"] = email_to
        if schedule.account_group_name:
            entry["account_group_name"] = schedule.account_group_name
        if schedule.account_group_limit:
            entry["account_group_limit"] = schedule.account_group_limit
        schedules_out.append(entry)
    return schedules_out


def _coerce_delivery_day(report_type: str, delivery_day: str) -> Any:
    """Monthly delivery days are integers in config; weekly stay strings."""
    if report_type == "monthly" and delivery_day.isdigit():
        return int(delivery_day)
    return delivery_day
