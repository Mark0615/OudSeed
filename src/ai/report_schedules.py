"""Client-level AI report schedule helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReportSchedule:
    """Resolved client-level report schedule."""

    schedule_id: str
    client_id: str
    report_type: str
    delivery_day: Any
    channel: str = "email"
    timezone: str | None = None
    depth: str = "standard"
    email_to: str | None = None
    account_group_name: str | None = None
    account_group_limit: int | None = None
    enabled: bool = True


def find_report_schedule(config: dict[str, Any], schedule_id: str | None) -> ReportSchedule | None:
    """Return a resolved report schedule by id."""
    if not schedule_id:
        return None

    matches: list[ReportSchedule] = []
    for client in config.get("clients", []):
        if not isinstance(client, dict):
            continue
        client_id = client.get("client_id")
        for raw_schedule in client.get("report_schedules", []) or []:
            if not isinstance(raw_schedule, dict):
                continue
            if raw_schedule.get("schedule_id") == schedule_id:
                matches.append(_resolve_schedule(client_id=client_id, raw_schedule=raw_schedule))

    if not matches:
        raise ValueError(f"No report schedule matched AI_REPORT_SCHEDULE_ID={schedule_id!r}.")
    if len(matches) > 1:
        raise ValueError(f"Multiple report schedules matched AI_REPORT_SCHEDULE_ID={schedule_id!r}.")
    schedule = matches[0]
    if not schedule.enabled:
        raise ValueError(f"Report schedule is disabled: {schedule_id}")
    return schedule


def list_report_schedules(config: dict[str, Any]) -> list[ReportSchedule]:
    """Return all configured client-level report schedules."""
    schedules: list[ReportSchedule] = []
    for client in config.get("clients", []):
        if not isinstance(client, dict):
            continue
        client_id = client.get("client_id")
        for raw_schedule in client.get("report_schedules", []) or []:
            if isinstance(raw_schedule, dict):
                schedules.append(_resolve_schedule(client_id=client_id, raw_schedule=raw_schedule))
    return schedules


def format_report_schedule_lines(schedules: list[ReportSchedule]) -> list[str]:
    """Return printable schedule metadata without exposing recipients."""
    lines = [f"ai_report_schedules=true schedule_count={len(schedules)}"]
    for index, schedule in enumerate(schedules, start=1):
        lines.append(
            "ai_report_schedule="
            f"{index} schedule_id={schedule.schedule_id} "
            f"client_id={schedule.client_id} "
            f"enabled={str(schedule.enabled).lower()} "
            f"report_type={schedule.report_type} "
            f"delivery_day={schedule.delivery_day} "
            f"timezone={schedule.timezone or '-'} "
            f"channel={schedule.channel} "
            f"depth={schedule.depth} "
            f"account_group_name={schedule.account_group_name or '-'} "
            f"account_group_limit={schedule.account_group_limit or '-'} "
            f"has_email_to={str(bool(schedule.email_to)).lower()}"
        )
    return lines


def _resolve_schedule(client_id: str, raw_schedule: dict[str, Any]) -> ReportSchedule:
    """Build a typed schedule object from config data."""
    return ReportSchedule(
        schedule_id=str(raw_schedule["schedule_id"]),
        client_id=client_id,
        report_type=str(raw_schedule["report_type"]),
        delivery_day=raw_schedule["delivery_day"],
        channel=str(raw_schedule.get("channel", "email")),
        timezone=raw_schedule.get("timezone"),
        depth=str(raw_schedule.get("depth", "standard")),
        email_to=raw_schedule.get("email_to"),
        account_group_name=raw_schedule.get("account_group_name"),
        account_group_limit=raw_schedule.get("account_group_limit"),
        enabled=bool(raw_schedule.get("enabled", True)),
    )
