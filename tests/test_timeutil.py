from datetime import date, datetime, timezone

from funnellens.timeutil import (
    day_windows,
    from_lsq_utc_string,
    ist_day_bounds,
    month_bounds,
    to_lsq_utc_string,
)


def test_ist_day_bounds_normal_day():
    start, end = ist_day_bounds(date(2026, 9, 10))
    # 00:00:00 IST = 18:30:00 UTC the previous day (IST is UTC+5:30)
    assert start == datetime(2026, 9, 9, 18, 30, 0, tzinfo=timezone.utc)
    # 23:59:59 IST = 18:29:59 UTC the same day
    assert end == datetime(2026, 9, 10, 18, 29, 59, tzinfo=timezone.utc)


def test_ist_day_bounds_month_end():
    start, end = ist_day_bounds(date(2026, 1, 31))
    assert start == datetime(2026, 1, 30, 18, 30, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 1, 31, 18, 29, 59, tzinfo=timezone.utc)


def test_ist_day_bounds_leap_year_feb_29():
    start, end = ist_day_bounds(date(2028, 2, 29))
    assert start.date() == date(2028, 2, 28)
    assert end.date() == date(2028, 2, 29)


def test_to_lsq_utc_string_from_aware_ist():
    dt = datetime(2026, 9, 10, 5, 30, 0, tzinfo=timezone.utc)
    assert to_lsq_utc_string(dt) == "2026-09-10 05:30:00"


def test_from_lsq_utc_string_returns_ist_aware():
    result = from_lsq_utc_string("2026-08-03 05:30:00.000")
    assert result.tzinfo is not None
    # 05:30:00 UTC = 11:00:00 IST
    assert result.hour == 11
    assert result.minute == 0


def test_round_trip_utc_string():
    original = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
    s = to_lsq_utc_string(original)
    parsed = from_lsq_utc_string(s)
    assert parsed.astimezone(timezone.utc) == original


def test_day_windows_spans_multiple_days():
    windows = day_windows(date(2026, 9, 1), date(2026, 9, 3))
    assert len(windows) == 3
    assert windows[0][0] == ist_day_bounds(date(2026, 9, 1))[0]
    assert windows[2][1] == ist_day_bounds(date(2026, 9, 3))[1]


def test_day_windows_single_day():
    windows = day_windows(date(2026, 9, 1), date(2026, 9, 1))
    assert len(windows) == 1


def test_day_windows_rejects_reversed_range():
    import pytest

    with pytest.raises(ValueError):
        day_windows(date(2026, 9, 5), date(2026, 9, 1))


def test_month_bounds_regular_month():
    start, end = month_bounds(date(2026, 9, 15))
    assert start == ist_day_bounds(date(2026, 9, 1))[0]
    assert end == ist_day_bounds(date(2026, 9, 30))[1]


def test_month_bounds_february_leap_year():
    start, end = month_bounds(date(2028, 2, 10))
    assert end == ist_day_bounds(date(2028, 2, 29))[1]


def test_month_bounds_december_year_rollover():
    start, end = month_bounds(date(2026, 12, 15))
    assert start == ist_day_bounds(date(2026, 12, 1))[0]
    assert end == ist_day_bounds(date(2026, 12, 31))[1]
