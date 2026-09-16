"""IST <-> UTC helpers and date window generation.

A "day" per README Critical Rule 2 is 00:00:00 IST through 23:59:59 IST.
LeadSquared's API takes and returns UTC as naive "yyyy-MM-dd HH:mm:ss" strings
(no timezone marker) -- see docs/LOGIC_SPEC.md section 1 and section 7.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")
LSQ_FORMAT = "%Y-%m-%d %H:%M:%S"


def ist_day_bounds(day: date) -> tuple[datetime, datetime]:
    """Returns (start_utc, end_utc) for 00:00:00 IST through 23:59:59 IST on `day`, as UTC-aware datetimes."""
    start_ist = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=IST)
    end_ist = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=IST)
    return start_ist.astimezone(UTC), end_ist.astimezone(UTC)


def to_lsq_utc_string(dt: datetime) -> str:
    """Formats an aware or naive-UTC datetime as LeadSquared's "yyyy-MM-dd HH:mm:ss" UTC string."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return dt.strftime(LSQ_FORMAT)


def from_lsq_utc_string(s: str) -> datetime:
    """Parses a naive LeadSquared UTC string and returns an IST-aware datetime."""
    naive = datetime.strptime(s.strip()[:19], LSQ_FORMAT)
    return naive.replace(tzinfo=UTC).astimezone(IST)


def day_windows(from_date: date, to_date: date) -> list[tuple[datetime, datetime]]:
    """Yields one (start_utc, end_utc) pair per IST calendar day from from_date through to_date, inclusive."""
    if to_date < from_date:
        raise ValueError(f"to_date ({to_date}) is before from_date ({from_date})")
    windows = []
    current = from_date
    while current <= to_date:
        windows.append(ist_day_bounds(current))
        current += timedelta(days=1)
    return windows


def month_bounds(day: date) -> tuple[datetime, datetime]:
    """Returns (start_utc, end_utc) for the IST calendar month containing `day`."""
    month_start = date(day.year, day.month, 1)
    if day.month == 12:
        next_month_start = date(day.year + 1, 1, 1)
    else:
        next_month_start = date(day.year, day.month + 1, 1)
    month_end = next_month_start - timedelta(days=1)
    return ist_day_bounds(month_start)[0], ist_day_bounds(month_end)[1]
