"""Tests for date utility helpers."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.utils.date_utils import (
    _get_default_report_period_start_for_now,
    _get_default_sync_range_for_now,
    _today_in_timezone,
    get_default_report_period_start,
    get_default_sync_range,
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


def test_get_default_report_period_start_rejects_unknown_type() -> None:
    """Unknown AI report types fail loudly."""
    with pytest.raises(ValueError, match="report_type"):
        get_default_report_period_start("daily")


def test_invalid_timezone_raises_error() -> None:
    """Invalid IANA timezone names raise an exception from zoneinfo."""
    with pytest.raises(Exception):
        today_in_timezone("Not/A_Timezone")
