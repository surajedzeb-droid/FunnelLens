"""Final Count report: one row per active counselor per month (LOGIC_SPEC.md section 3.6).

Overdues_Monthly/Overdues_Total are the "live snapshot" overdue definition (LOGIC_SPEC.md
6.1) -- fetched fresh via one LSQClient.get_tasks_for_owner call per counselor, evaluated
against "now" at report-generation time (Resolved Decision 5: this must reflect the moment
of generation, not a historically cached pull). context.client is therefore required for
this report; every other report here is a pure function of `dataset`.

`Till Date` is always blank, matching the Apps Script exactly (Resolved Decision 4).
No Task_Monthly and No Task_Total are numerically the same figure -- both are month-to-date
sums, "_Total" here does NOT mean all-time (LOGIC_SPEC.md section 3.6, item 8)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from funnellens.extract import Dataset
from funnellens.reports import ReportContext, ReportError, ReportResult
from funnellens.reports._shared import active_counselor_names, safe_pct, task_metrics_for_day

COLUMNS = [
    "Till Date", "Counselor Name", "Created On", "Modified On", "Overdues_Monthly", "Overdues_Total",
    "No Task_Monthly", "No Task_Total", "Enrolled", "Conversion %", "Referral (This Month)",
    "Direct Walk In (This Month)",
]


def _month_to_date_count(df: pd.DataFrame, month_start: date, to_date: date) -> dict:
    if df.empty:
        return {}
    window = df[(df["ist_date"] >= month_start) & (df["ist_date"] <= to_date)]
    return window.groupby("counselor_name").size().to_dict()


def _no_task_month_to_date(dataset: Dataset, month_start: date, to_date: date, now) -> dict:
    """Month-to-date sum of Lead Funnel's per-day "No Task" column (LOGIC_SPEC.md 3.1, 3.6).
    `now` only affects task_metrics_for_day's overdue count, which isn't used here."""
    created = dataset.leads_created
    if created.empty:
        return {}
    totals: dict[str, int] = {}
    for day in sorted(created.loc[(created["ist_date"] >= month_start) & (created["ist_date"] <= to_date),
                                   "ist_date"].unique()):
        for counselor, metrics in task_metrics_for_day(dataset, day, now).items():
            totals[counselor] = totals.get(counselor, 0) + metrics["no_task"]
    return totals


def _live_overdue_counts(context: ReportContext, active_users: pd.DataFrame) -> dict[str, tuple[int, int]]:
    """{counselor_name: (overdues_this_month, overdues_total)} via one live Task.svc/Retrieve
    call per counselor (LOGIC_SPEC.md 1.2, 6.1). Task.svc/Retrieve already filters to
    Pending server-side (StatusCode: 0), so only the due-date-vs-now check is needed here."""
    if context.client is None:
        raise ReportError("final_count needs a live LSQClient (ReportContext.client) for Overdues_Monthly/Overdues_Total")
    from funnellens.reports._shared import parse_due_date

    month_start = context.run_date.replace(day=1)
    now = context.run_at
    results: dict[str, tuple[int, int]] = {}
    for _, user in active_users.iterrows():
        owner_id, counselor = user.get("owner_id"), user.get("counselor_name")
        total = this_month = 0
        for task in context.client.get_tasks_for_owner(owner_id):
            due = parse_due_date(task.get("DueDate"))
            if due is None or due >= now:
                continue
            total += 1
            if due.date() >= month_start:
                this_month += 1
        results[counselor] = (this_month, total)
    return results


def build(dataset: Dataset, from_date: date, to_date: date, context: ReportContext) -> ReportResult:
    month_start = to_date.replace(day=1)
    counselors = active_counselor_names(dataset)
    created, modified, enrolments = dataset.leads_created, dataset.leads_modified, dataset.enrolments

    created_m = _month_to_date_count(created, month_start, to_date)
    modified_m = _month_to_date_count(modified, month_start, to_date)
    no_task_m = _no_task_month_to_date(dataset, month_start, to_date, context.run_at)
    enrolled_m = (_month_to_date_count(enrolments, month_start, to_date)
                  if "ist_date" in enrolments.columns else {})
    referral_m = (_month_to_date_count(created[created["source"].str.lower() == "referrals"], month_start, to_date)
                  if not created.empty else {})
    walkin_m = (_month_to_date_count(created[created["source"].str.lower() == "direct walk in"], month_start, to_date)
                if not created.empty else {})

    users = dataset.users
    active_users = users[users["is_active"]] if not users.empty and "is_active" in users.columns else users
    overdue_counts = _live_overdue_counts(context, active_users)

    rows = []
    for counselor in counselors:
        created_n = created_m.get(counselor, 0)
        enrolled_n = enrolled_m.get(counselor, 0)
        overdues_month, overdues_total = overdue_counts.get(counselor, (0, 0))
        no_task_n = no_task_m.get(counselor, 0)
        rows.append({
            "Till Date": "", "Counselor Name": counselor,
            "Created On": created_n, "Modified On": modified_m.get(counselor, 0),
            "Overdues_Monthly": overdues_month, "Overdues_Total": overdues_total,
            "No Task_Monthly": no_task_n, "No Task_Total": no_task_n,
            "Enrolled": enrolled_n, "Conversion %": safe_pct(enrolled_n, created_n),
            "Referral (This Month)": referral_m.get(counselor, 0),
            "Direct Walk In (This Month)": walkin_m.get(counselor, 0),
            "is_total": False,
        })
    df = pd.DataFrame(rows, columns=[*COLUMNS, "is_total"])
    return ReportResult(key="final", title="Final Count", date_basis="Month", dataframe=df)
