"""Date helpers for sync windows."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


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
