"""Date helpers for sync windows."""

from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

WEEKDAY_INDEXES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def today_in_timezone(timezone: str) -> date:
    """Return today's date in the given IANA timezone."""
    return _today_in_timezone(timezone)


def get_default_sync_range(
    days_back: int = 7,
    timezone: str = "Asia/Taipei",
) -> tuple[str, str]:
    """Return the default inclusive sync range as YYYY-MM-DD strings.

    The end date is yesterday in the requested timezone. The start date is
    `days_back` days before the end date, matching the MVP backfill strategy.
    """
    if days_back < 0:
        raise ValueError("days_back must be greater than or equal to 0.")

    end_date = today_in_timezone(timezone) - timedelta(days=1)
    start_date = end_date - timedelta(days=days_back)

    return start_date.isoformat(), end_date.isoformat()


def get_default_report_period_start(
    report_type: str,
    timezone: str = "Asia/Taipei",
) -> str:
    """Return the latest complete report period start date."""
    return _get_default_report_period_start_for_now(
        report_type=report_type,
        timezone=timezone,
        now=datetime.now(tz=ZoneInfo(timezone)),
    )


def get_scheduled_report_period_start(
    report_type: str,
    delivery_day: Any,
    timezone: str = "Asia/Taipei",
) -> str:
    """Return the latest complete report period for a configured delivery day."""
    return _get_scheduled_report_period_start_for_now(
        report_type=report_type,
        delivery_day=delivery_day,
        timezone=timezone,
        now=datetime.now(tz=ZoneInfo(timezone)),
    )


def _today_in_timezone(timezone: str, now: datetime | None = None) -> date:
    """Return today's date in a timezone, with injectable time for tests."""
    zone = ZoneInfo(timezone)
    current_time = now or datetime.now(tz=zone)

    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=zone)

    return current_time.astimezone(zone).date()


def _get_default_sync_range_for_now(
    days_back: int,
    timezone: str,
    now: datetime,
) -> tuple[str, str]:
    """Return sync range for a fixed datetime used by tests."""
    if days_back < 0:
        raise ValueError("days_back must be greater than or equal to 0.")

    end_date = _today_in_timezone(timezone, now=now) - timedelta(days=1)
    start_date = end_date - timedelta(days=days_back)

    return start_date.isoformat(), end_date.isoformat()


def _get_default_report_period_start_for_now(
    report_type: str,
    timezone: str,
    now: datetime,
) -> str:
    """Return report period start for a fixed datetime used by tests."""
    today = _today_in_timezone(timezone, now=now)
    if report_type == "weekly":
        current_week_start = today - timedelta(days=today.weekday())
        return (current_week_start - timedelta(days=7)).isoformat()
    if report_type == "monthly":
        current_month_start = today.replace(day=1)
        previous_month_end = current_month_start - timedelta(days=1)
        return previous_month_end.replace(day=1).isoformat()
    raise ValueError("report_type must be 'weekly' or 'monthly'.")


def _get_scheduled_report_period_start_for_now(
    report_type: str,
    delivery_day: Any,
    timezone: str,
    now: datetime,
) -> str:
    """Return period start for a cadence-specific delivery day."""
    today = _today_in_timezone(timezone, now=now)
    if report_type == "weekly":
        weekday = _parse_weekday(delivery_day)
        days_since_delivery = (today.weekday() - weekday) % 7
        latest_delivery_date = today - timedelta(days=days_since_delivery)
        return (latest_delivery_date - timedelta(days=7)).isoformat()

    if report_type == "monthly":
        day = _parse_month_day(delivery_day)
        delivery_this_month = _month_delivery_date(today.year, today.month, day)
        if today >= delivery_this_month:
            latest_delivery_date = delivery_this_month
        else:
            previous_month = today.replace(day=1) - timedelta(days=1)
            latest_delivery_date = _month_delivery_date(
                previous_month.year,
                previous_month.month,
                day,
            )
        current_period_start = latest_delivery_date.replace(day=1)
        previous_period_end = current_period_start - timedelta(days=1)
        return previous_period_end.replace(day=1).isoformat()

    raise ValueError("report_type must be 'weekly' or 'monthly'.")


def _parse_weekday(value: Any) -> int:
    """Parse a weekly delivery day into Python's Monday-based weekday index."""
    if isinstance(value, int) and not isinstance(value, bool):
        if 0 <= value <= 6:
            return value
        raise ValueError("weekly delivery_day integer must be between 0 and 6.")

    normalized = str(value).strip().lower()
    if normalized in WEEKDAY_INDEXES:
        return WEEKDAY_INDEXES[normalized]
    raise ValueError("weekly delivery_day must be monday through sunday.")


def _parse_month_day(value: Any) -> int:
    """Parse a monthly delivery day."""
    try:
        day = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("monthly delivery_day must be an integer from 1 to 31.") from exc

    if 1 <= day <= 31:
        return day
    raise ValueError("monthly delivery_day must be an integer from 1 to 31.")


def _month_delivery_date(year: int, month: int, day: int) -> date:
    """Return the delivery date, clamped to the month's final day."""
    last_day = monthrange(year, month)[1]
    return date(year, month, min(day, last_day))
