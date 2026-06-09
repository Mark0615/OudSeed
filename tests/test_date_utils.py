"""Tests for date utility helpers."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from src.utils.date_utils import (
    _get_default_report_period_start_for_now,
    _get_default_sync_range_for_now,
    _get_scheduled_report_period_start_for_now,
    _today_in_timezone,
    get_default_report_period_start,
    get_default_sync_range,
    is_report_due_today,
    today_in_timezone,
)


def test_today_in_timezone_returns_date() -> None:
    """today_in_timezone returns a date object."""
    assert today_in_timezone("Asia/Taipei").isoformat()


def test_today_in_timezone_converts_from_utc_to_taipei() -> None:
    """A UTC timestamp can already be the next calendar day in Taipei."""
    now = datetime(2026, 5, 3, 16, 30, tzinfo=ZoneInfo("UTC"))

    assert _today_in_timezone("Asia/Taipei", now=now).isoformat() == "2026-05-04"


def test_get_default_sync_range_for_taipei() -> None:
    """Default range ends yesterday and starts seven days before that."""
    now = datetime(2026, 5, 4, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    assert _get_default_sync_range_for_now(
        days_back=7,
        timezone="Asia/Taipei",
        now=now,
    ) == ("2026-04-26", "2026-05-03")


def test_get_default_sync_range_supports_zero_days_back() -> None:
    """days_back=0 returns only yesterday."""
    now = datetime(2026, 5, 4, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    assert _get_default_sync_range_for_now(
        days_back=0,
        timezone="Asia/Taipei",
        now=now,
    ) == ("2026-05-03", "2026-05-03")


def test_get_default_sync_range_rejects_negative_days_back() -> None:
    """Negative backfill windows are rejected."""
    with pytest.raises(ValueError, match="days_back must be greater than or equal to 0"):
        get_default_sync_range(days_back=-1)


def test_get_default_weekly_report_period_start() -> None:
    """Weekly AI reports default to the previous complete Monday-starting week."""
    now = datetime(2026, 5, 9, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    assert _get_default_report_period_start_for_now(
        report_type="weekly",
        timezone="Asia/Taipei",
        now=now,
    ) == "2026-04-27"


def test_get_default_monthly_report_period_start() -> None:
    """Monthly AI reports default to the first day of the previous month."""
    now = datetime(2026, 5, 9, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    assert _get_default_report_period_start_for_now(
        report_type="monthly",
        timezone="Asia/Taipei",
        now=now,
    ) == "2026-04-01"


def test_get_scheduled_weekly_report_period_start_uses_delivery_day() -> None:
    """Weekly schedule periods end the day before the latest configured delivery day."""
    now = datetime(2026, 5, 27, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    assert _get_scheduled_report_period_start_for_now(
        report_type="weekly",
        delivery_day="wednesday",
        timezone="Asia/Taipei",
        now=now,
    ) == "2026-05-20"


def test_get_scheduled_monthly_report_period_start_waits_for_delivery_day() -> None:
    """Monthly schedule periods advance only after the configured delivery day."""
    now = datetime(2026, 5, 5, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    assert _get_scheduled_report_period_start_for_now(
        report_type="monthly",
        delivery_day=10,
        timezone="Asia/Taipei",
        now=now,
    ) == "2026-03-01"


def test_get_scheduled_monthly_report_period_start_after_delivery_day() -> None:
    """Monthly schedule periods use the previous complete month after delivery day."""
    now = datetime(2026, 5, 27, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    assert _get_scheduled_report_period_start_for_now(
        report_type="monthly",
        delivery_day=10,
        timezone="Asia/Taipei",
        now=now,
    ) == "2026-04-01"


def test_get_default_report_period_start_rejects_unknown_type() -> None:
    """Unknown AI report types fail loudly."""
    with pytest.raises(ValueError, match="report_type"):
        get_default_report_period_start("daily")


def test_invalid_timezone_raises_error() -> None:
    """Invalid IANA timezone names raise an exception from zoneinfo."""
    with pytest.raises(ZoneInfoNotFoundError):
        today_in_timezone("Not/A_Timezone")


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def test_is_report_due_today_weekly_only_on_matching_weekday() -> None:
    now = datetime(2026, 6, 10, 9, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    today_name = _WEEKDAYS[now.weekday()]
    other_name = _WEEKDAYS[(now.weekday() + 1) % 7]
    assert is_report_due_today("weekly", today_name, "Asia/Taipei", now=now) is True
    assert is_report_due_today("weekly", other_name, "Asia/Taipei", now=now) is False


def test_is_report_due_today_monthly_on_day_of_month() -> None:
    now = datetime(2026, 6, 1, 9, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    assert is_report_due_today("monthly", 1, "Asia/Taipei", now=now) is True
    assert is_report_due_today("monthly", 2, "Asia/Taipei", now=now) is False


def test_is_report_due_today_monthly_clamps_to_last_day() -> None:
    # Day 31 in 30-day June fires on the 30th, not the 29th.
    due = datetime(2026, 6, 30, 9, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    not_due = datetime(2026, 6, 29, 9, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    assert is_report_due_today("monthly", 31, "Asia/Taipei", now=due) is True
    assert is_report_due_today("monthly", 31, "Asia/Taipei", now=not_due) is False


def test_is_report_due_today_respects_timezone() -> None:
    # 23:30 UTC on May 31 is already June 1 in Taipei (+8) -> a day-1 monthly is due.
    now = datetime(2026, 5, 31, 23, 30, tzinfo=ZoneInfo("UTC"))
    assert is_report_due_today("monthly", 1, "Asia/Taipei", now=now) is True


def test_is_report_due_today_rejects_unknown_report_type() -> None:
    now = datetime(2026, 6, 1, 9, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    with pytest.raises(ValueError):
        is_report_due_today("daily", 1, "Asia/Taipei", now=now)
