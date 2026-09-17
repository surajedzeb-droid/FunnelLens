"""Leads / opportunities / tasks / users pulls from LeadSquared for a date range.

Pulls are split into IST day windows (timeutil.day_windows) and cached per
(entity, day) via cache.py. Stage/status/enrolled-date come from the
Opportunity, joined to leads by lead_id, matching the Apps Script
(docs/LOGIC_SPEC.md section 1.6). Overdue-task fetching (RetrieveTaskByLeadId,
LOGIC_SPEC.md 1.3) has no record cap to hit -- it is one call per lead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import partial
from typing import Callable

import pandas as pd

from funnellens.cache import load_cached, save_cache
from funnellens.lsq_client import LSQClient
from funnellens.settings import Settings
from funnellens.timeutil import day_windows

ProgressCallback = Callable[[str, int, int], None]


@dataclass
class Dataset:
    leads_created: pd.DataFrame
    leads_modified: pd.DataFrame
    opportunities: pd.DataFrame
    enrolments: pd.DataFrame
    tasks: pd.DataFrame
    users: pd.DataFrame


def _lead_include_csv(settings: Settings) -> str:
    f = settings.fields
    return ",".join(
        f[key] for key in ("lead_id", "owner_id", "owner_name", "created_on", "modified_on", "source", "course")
    )


def _cached(entity: str, day: date, force_refresh: bool, compute: Callable[[], pd.DataFrame]) -> pd.DataFrame:
    if not force_refresh:
        cached = load_cached(entity, day)
        if cached is not None:
            return cached
    df = compute()
    save_cache(entity, day, df)
    return df


def _fetch_leads_window(entity: str, day: date, start, end, include_csv: str, force_refresh: bool,
                         search_fn: Callable[..., list[dict]]) -> pd.DataFrame:
    return _cached(entity, day, force_refresh, lambda: pd.DataFrame(search_fn(start, end, include_csv)))


def _fetch_enrolments_window(client: LSQClient, day: date, start, end, force_refresh: bool) -> pd.DataFrame:
    def compute() -> pd.DataFrame:
        # The API returns no enrolled-date field per record (it's only the search's own
        # filter parameter) -- tag each day's window explicitly, or Reports/Final Count/
        # Source Wise Enrolment can't attribute an enrolment to a day or month at all.
        df = pd.DataFrame(client.search_opportunities_by_enrolled_date(start, end))
        if not df.empty:
            df["ist_date"] = day
        return df

    return _cached("enrolments", day, force_refresh, compute)


def _fetch_opportunities_for_day(client: LSQClient, day: date, lead_ids: list[str], force_refresh: bool) -> pd.DataFrame:
    def compute() -> pd.DataFrame:
        if not lead_ids:
            return pd.DataFrame(columns=["lead_id"])
        results = client.run_parallel([partial(client.get_opportunities_of_lead, lid) for lid in lead_ids])
        rows = [{"lead_id": lead_id, **(opp or {})} for lead_id, opp in zip(lead_ids, results)]
        return pd.DataFrame(rows)

    return _cached("opportunities", day, force_refresh, compute)


def _fetch_tasks_for_day(client: LSQClient, day: date, lead_ids: list[str], force_refresh: bool) -> pd.DataFrame:
    def compute() -> pd.DataFrame:
        if not lead_ids:
            return pd.DataFrame(columns=["lead_id"])
        results = client.run_parallel([partial(client.get_tasks_for_lead, lid) for lid in lead_ids])
        rows = [{**task, "lead_id": lead_id} for lead_id, tasks in zip(lead_ids, results) for task in tasks]
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["lead_id"])

    return _cached("tasks", day, force_refresh, compute)


def _filter_by_owners(dataset: Dataset, settings: Settings, owners: list[str]) -> Dataset:
    owner_field = settings.fields["owner_name"]

    def keep(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or owner_field not in df.columns:
            return df
        return df[df[owner_field].isin(owners)].reset_index(drop=True)

    dataset.leads_created = keep(dataset.leads_created)
    dataset.leads_modified = keep(dataset.leads_modified)
    return dataset


def fetch_dataset(from_date: date, to_date: date, settings: Settings, client: LSQClient | None = None,
                   owners: list[str] | None = None, progress_callback: ProgressCallback | None = None,
                   force_refresh: bool = False) -> Dataset:
    """Pulls leads, opportunities, enrolments, tasks and users for [from_date, to_date] (IST, inclusive).

    Day windows are fetched in parallel (README Critical Rule 6). Per-lead opportunity/task
    lookups run in parallel within each day, one day at a time, to keep total concurrency
    bounded by api.max_workers rather than squaring it.
    """
    client = client or LSQClient(settings)
    include_csv = _lead_include_csv(settings)
    lead_id_field = settings.fields["lead_id"]
    days = [from_date + timedelta(days=i) for i in range((to_date - from_date).days + 1)]
    windows = day_windows(from_date, to_date)

    def report(stage: str, done: int, total: int) -> None:
        if progress_callback:
            progress_callback(stage, done, total)

    leads_calls = []
    for day, (start, end) in zip(days, windows):
        leads_calls.append(partial(_fetch_leads_window, "leads_created", day, start, end, include_csv,
                                    force_refresh, client.search_leads_created_between))
        leads_calls.append(partial(_fetch_leads_window, "leads_modified", day, start, end, include_csv,
                                    force_refresh, client.search_leads_modified_between))
    leads_results = client.run_parallel(leads_calls)
    created_frames, modified_frames = leads_results[0::2], leads_results[1::2]
    report("leads", len(days), len(days))

    enrolment_frames = client.run_parallel(
        [partial(_fetch_enrolments_window, client, day, start, end, force_refresh)
         for day, (start, end) in zip(days, windows)]
    )
    report("enrolments", len(days), len(days))

    opportunity_frames, task_frames = [], []
    for i, (day, created_df, modified_df) in enumerate(zip(days, created_frames, modified_frames)):
        created_ids = created_df[lead_id_field].tolist() if not created_df.empty else []
        modified_ids = modified_df[lead_id_field].tolist() if not modified_df.empty else []
        opp_ids = list(dict.fromkeys(created_ids + modified_ids))
        opportunity_frames.append(_fetch_opportunities_for_day(client, day, opp_ids, force_refresh))
        task_frames.append(_fetch_tasks_for_day(client, day, created_ids, force_refresh))
        report("opportunities", i + 1, len(days))

    users_df = pd.DataFrame(client.get_users())

    def concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    dataset = Dataset(
        leads_created=concat(created_frames),
        leads_modified=concat(modified_frames),
        opportunities=concat(opportunity_frames),
        enrolments=concat(enrolment_frames),
        tasks=concat(task_frames),
        users=users_df,
    )
    if owners:
        dataset = _filter_by_owners(dataset, settings, owners)
    return dataset
