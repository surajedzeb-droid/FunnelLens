"""Parquet cache read/write for raw LeadSquared pulls.

One file per (entity, IST date) under data/cache/. A day is cache-valid once it
is at least 2 days old -- today and yesterday can still change, so they are
always refetched (README Section 4.2 acceptance: no stale-looking numbers).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"


def cache_path(entity: str, day: date) -> Path:
    return CACHE_DIR / entity / f"{day.isoformat()}.parquet"


def is_cache_valid(day: date, today: date | None = None) -> bool:
    today = today or date.today()
    return (today - day).days >= 2


def load_cached(entity: str, day: date, today: date | None = None) -> pd.DataFrame | None:
    """Returns the cached DataFrame for (entity, day), or None if not cached or not yet cache-valid."""
    if not is_cache_valid(day, today):
        return None
    path = cache_path(entity, day)
    if not path.exists():
        return None
    return pd.read_parquet(path)


def save_cache(entity: str, day: date, df: pd.DataFrame) -> None:
    path = cache_path(entity, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
