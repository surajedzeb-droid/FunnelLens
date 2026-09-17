from datetime import date

import pandas as pd
import pytest

from funnellens import cache


@pytest.fixture(autouse=True)
def isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")


def test_is_cache_valid_today_and_yesterday_are_never_valid():
    today = date(2026, 9, 17)
    assert cache.is_cache_valid(today, today=today) is False
    assert cache.is_cache_valid(date(2026, 9, 16), today=today) is False


def test_is_cache_valid_two_days_old_is_valid():
    today = date(2026, 9, 17)
    assert cache.is_cache_valid(date(2026, 9, 15), today=today) is True


def test_save_then_load_round_trips():
    day = date(2026, 9, 1)
    df = pd.DataFrame({"ProspectID": ["1", "2"]})
    cache.save_cache("leads_created", day, df)
    loaded = cache.load_cached("leads_created", day, today=date(2026, 9, 17))
    pd.testing.assert_frame_equal(loaded, df)


def test_load_returns_none_when_not_cached():
    assert cache.load_cached("leads_created", date(2026, 9, 1), today=date(2026, 9, 17)) is None


def test_load_returns_none_when_not_yet_cache_valid():
    day = date(2026, 9, 16)
    cache.save_cache("leads_created", day, pd.DataFrame({"x": [1]}))
    assert cache.load_cached("leads_created", day, today=date(2026, 9, 17)) is None
