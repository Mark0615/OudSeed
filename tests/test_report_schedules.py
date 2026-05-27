"""Tests for client-level AI report schedule helpers."""

import pytest

from src.ai.report_schedules import find_report_schedule


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
