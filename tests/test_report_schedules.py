"""Tests for client-level AI report schedule helpers."""

import pytest

from src.ai.report_schedules import (
    find_report_schedule,
    format_report_schedule_lines,
    list_report_schedules,
)


def test_find_report_schedule_resolves_client_schedule() -> None:
    """Schedules inherit the parent client id and expose report defaults."""
    config = {
        "clients": [
            {
                "client_id": "demo_client_001",
                "report_schedules": [
                    {
                        "schedule_id": "monthly_email_default",
                        "report_type": "monthly",
                        "delivery_day": 10,
                        "channel": "email",
                        "email_to": "recipient@example.com",
                        "depth": "deep",
                        "account_group_name": "Example Account",
                        "account_group_limit": 1,
                    }
                ],
            }
        ]
    }

    schedule = find_report_schedule(config, "monthly_email_default")

    assert schedule is not None
    assert schedule.client_id == "demo_client_001"
    assert schedule.report_type == "monthly"
    assert schedule.delivery_day == 10
    assert schedule.email_to == "recipient@example.com"
    assert schedule.depth == "deep"
    assert schedule.account_group_name == "Example Account"
    assert schedule.account_group_limit == 1


def test_find_report_schedule_returns_none_when_unset() -> None:
    """Unset schedule id preserves legacy env-based behavior."""
    assert find_report_schedule({"clients": []}, None) is None


def test_find_report_schedule_rejects_missing_schedule() -> None:
    """Unknown schedule ids fail loudly."""
    with pytest.raises(ValueError, match="No report schedule matched"):
        find_report_schedule({"clients": []}, "missing")


def test_find_report_schedule_rejects_disabled_schedule() -> None:
    """Disabled schedules are not runnable."""
    config = {
        "clients": [
            {
                "client_id": "demo_client_001",
                "report_schedules": [
                    {
                        "schedule_id": "weekly_email_default",
                        "enabled": False,
                        "report_type": "weekly",
                        "delivery_day": "monday",
                    }
                ],
            }
        ]
    }

    with pytest.raises(ValueError, match="disabled"):
        find_report_schedule(config, "weekly_email_default")


def test_list_report_schedules_returns_all_schedules() -> None:
    """Schedule discovery includes enabled and disabled schedule configs."""
    config = {
        "clients": [
            {
                "client_id": "demo_client_001",
                "report_schedules": [
                    {
                        "schedule_id": "monthly_email_default",
                        "report_type": "monthly",
                        "delivery_day": 1,
                    },
                    {
                        "schedule_id": "weekly_email_default",
                        "enabled": False,
                        "report_type": "weekly",
                        "delivery_day": "monday",
                    },
                ],
            }
        ]
    }

    schedules = list_report_schedules(config)

    assert [schedule.schedule_id for schedule in schedules] == [
        "monthly_email_default",
        "weekly_email_default",
    ]
    assert schedules[0].enabled is True
    assert schedules[1].enabled is False


def test_format_report_schedule_lines_hides_recipients() -> None:
    """Schedule list output exposes metadata but not email recipients."""
    config = {
        "clients": [
            {
                "client_id": "demo_client_001",
                "report_schedules": [
                    {
                        "schedule_id": "monthly_email_default",
                        "report_type": "monthly",
                        "delivery_day": 10,
                        "channel": "email",
                        "email_to": "recipient@example.com",
                        "depth": "standard",
                        "account_group_name": "Example Account",
                        "account_group_limit": 1,
                    }
                ],
            }
        ]
    }

    output = "\n".join(format_report_schedule_lines(list_report_schedules(config)))

    assert "ai_report_schedules=true" in output
    assert "schedule_count=1" in output
    assert "schedule_id=monthly_email_default" in output
    assert "client_id=demo_client_001" in output
    assert "delivery_day=10" in output
    assert "account_group_name=Example Account" in output
    assert "account_group_limit=1" in output
    assert "has_email_to=true" in output
    assert "recipient@example.com" not in output
