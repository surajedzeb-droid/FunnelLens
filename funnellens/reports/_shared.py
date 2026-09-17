"""Shared day-block/rollup helpers for the day-based reports (Lead Funnel, Stage Wise,
Source Wise, Course Wise, Reports; LOGIC_SPEC.md section 3). Each of these puts one row
per active counselor per day, newest day first, with a Total row after each day's block.

Monthly/Yesterday columns are the pandas equivalent of the Sheet's SUMIFS formulas -- they
need every day from the month start through `to_date` (and the day before `from_date`, for
Yesterday columns) to be present in `dataset`. It is the caller's job to pull that much
history (README "pull once, compute many"); these helpers just sum/count whatever calendar
days are actually present, the same way a SUMIFS reads whatever rows exist in the sheet.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from funnellens.extract import Dataset
from funnellens.timeutil import from_lsq_utc_string


def active_counselor_names(dataset: Dataset) -> list[str]:
    users = dataset.users
    if users.empty:
        return []
    active = users[users["is_active"]] if "is_active" in users.columns else users
    return sorted(active["counselor_name"].dropna().unique())


def day_count(df: pd.DataFrame, date_col: str, group_col: str, day: date) -> dict:
    """COUNTIFS(group_col=<group>, date_col=day) per group value."""
    if df.empty:
        return {}
    return df[df[date_col] == day].groupby(group_col).size().to_dict()


def month_to_date_count(df: pd.DataFrame, date_col: str, group_col: str, as_of: date) -> dict:
    """SUMIFS/COUNTIFS(group_col=<group>, date_col in [month-start(as_of), as_of]) per group value."""
    if df.empty:
        return {}
    month_start = as_of.replace(day=1)
    window = df[(df[date_col] >= month_start) & (df[date_col] <= as_of)]
    return window.groupby(group_col).size().to_dict()


def safe_pct(numerator: float, denominator: float) -> float:
    """IF(denominator=0, 0, ROUND(numerator/denominator*100, 1)) -- every %% formula in LOGIC_SPEC.md."""
    if not denominator:
        return 0.0
    return round(numerator / denominator * 100, 1)


def order_newest_first(day_rows: dict[date, list[dict]], columns: list[str]) -> pd.DataFrame:
    """Concatenates day blocks (each a list of row dicts, its Total row already appended)
    into one DataFrame ordered newest day first."""
    rows = []
    for day in sorted(day_rows, reverse=True):
        rows.extend(day_rows[day])
    return pd.DataFrame(rows, columns=[*columns, "is_total"])


def task_metrics_for_day(dataset: Dataset, day: date, now: datetime) -> dict[str, dict[str, int]]:
    """Day-wise task metrics for leads created on `day` (LOGIC_SPEC.md section 6.2): per
    counselor, {"task": total tasks, "overdues": Pending tasks past due as of `now`,
    "no_task": leads with zero tasks at all}. Shared by lead_funnel.py and final_count.py
    so the two reports can never disagree on what "created that day's tasks" means."""
    created = dataset.leads_created
    tasks = dataset.tasks
    day_leads = created[created["ist_date"] == day] if not created.empty else created
    if day_leads.empty:
        return {}

    lead_to_counselor = day_leads.set_index("lead_id")["counselor_name"]
    day_lead_ids = set(day_leads["lead_id"])
    day_tasks = tasks[tasks["lead_id"].isin(day_lead_ids)] if not tasks.empty else tasks

    result = {name: {"task": 0, "overdues": 0, "no_task": 0} for name in day_leads["counselor_name"].unique()}
    leads_with_tasks: set = set()
    if not day_tasks.empty:
        for lead_id, group in day_tasks.groupby("lead_id"):
            counselor = lead_to_counselor.get(lead_id)
            if counselor is None:
                continue
            leads_with_tasks.add(lead_id)
            result[counselor]["task"] += len(group)
            overdue = group[(group["task_status"] == "Pending") & (group["task_due_date"] < now)]
            result[counselor]["overdues"] += len(overdue)
    for lead_id, counselor in lead_to_counselor.items():
        if lead_id not in leads_with_tasks:
            result[counselor]["no_task"] += 1
    return result


def build_dynamic_pivot_report(dataset: Dataset, from_date: date, to_date: date, value_field: str) -> pd.DataFrame:
    """Shared mechanism for Source Wise and Course Wise (LOGIC_SPEC.md sections 3.3-3.4): day
    x dynamic column, one column per distinct `value_field` value appearing in the range, in
    first-seen (oldest-day-first) order. normalize.py's canonicalize_column already merged
    case/whitespace variants globally, so no per-day canonicalization is needed here (unlike
    the Apps Script's own day-by-day canonicalize()). "(Blank)" is placed last, Total after it.
    """
    from datetime import timedelta

    created = dataset.leads_created
    counselors = active_counselor_names(dataset)
    days = [from_date + timedelta(days=i) for i in range((to_date - from_date).days + 1)]

    ordered_values: list[str] = []
    seen: set = set()
    if not created.empty:
        window = created[(created["ist_date"] >= from_date) & (created["ist_date"] <= to_date)].sort_values("ist_date")
        for value in window[value_field]:
            if value not in seen:
                seen.add(value)
                ordered_values.append(value)
    if "(Blank)" in ordered_values:
        ordered_values.remove("(Blank)")
        ordered_values.append("(Blank)")

    columns = ["Date", "Counselor Name", *ordered_values, "Total"]
    day_rows: dict[date, list[dict]] = {}
    for day in days:
        day_leads = created[created["ist_date"] == day] if not created.empty else created
        rows = []
        for counselor in counselors:
            counselor_leads = (day_leads[day_leads["counselor_name"] == counselor]
                                if not day_leads.empty else day_leads)
            counts = counselor_leads[value_field].value_counts().to_dict() if not counselor_leads.empty else {}
            row = {"Date": day, "Counselor Name": counselor}
            for value in ordered_values:
                row[value] = counts.get(value, 0)
            row["Total"] = sum(counts.get(v, 0) for v in ordered_values)
            row["is_total"] = False
            rows.append(row)
        day_df = pd.DataFrame(rows, columns=[*columns, "is_total"])
        total_row = {col: "" for col in columns}
        total_row["Counselor Name"] = "Total"
        for value in [*ordered_values, "Total"]:
            total_row[value] = day_df[value].sum() if not day_df.empty else 0
        total_row["is_total"] = True
        day_rows[day] = rows + [total_row]

    return order_newest_first(day_rows, columns)


def parse_due_date(value) -> datetime | None:
    if not value:
        return None
    try:
        return from_lsq_utc_string(value)
    except (ValueError, TypeError):
        return None
