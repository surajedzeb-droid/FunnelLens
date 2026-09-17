"""Lead Funnel report: daily and monthly Created, Modified, Task and Overdue counts,
one row per active counselor per day (LOGIC_SPEC.md section 3.1)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from funnellens.extract import Dataset
from funnellens.reports import ReportContext, ReportResult
from funnellens.reports._shared import (
    active_counselor_names, day_count, month_to_date_count, order_newest_first, safe_pct, task_metrics_for_day,
)

COLUMNS = [
    "Date", "Counselor Name", "Created On_Day wise", "Created On (Monthly)",
    "Modified On (Daily)", "Modified On (Monthly)", "Modified %_Monthly",
    "Overdues", "Task", "Overdues %", "No Task", "No Task %",
]
_SUM_COLUMNS = {"Created On_Day wise", "Modified On (Daily)", "Overdues", "Task", "No Task"}


def build(dataset: Dataset, from_date: date, to_date: date, context: ReportContext) -> ReportResult:
    created = dataset.leads_created
    modified = dataset.leads_modified
    counselors = active_counselor_names(dataset)
    days = [from_date + timedelta(days=i) for i in range((to_date - from_date).days + 1)]

    day_rows: dict[date, list[dict]] = {}
    for day in days:
        created_today = day_count(created, "ist_date", "counselor_name", day)
        modified_today = day_count(modified, "ist_date", "counselor_name", day)
        created_monthly = month_to_date_count(created, "ist_date", "counselor_name", day)
        modified_monthly = month_to_date_count(modified, "ist_date", "counselor_name", day)
        task_metrics = task_metrics_for_day(dataset, day, context.run_at)

        rows = []
        for counselor in counselors:
            created_n = created_today.get(counselor, 0)
            modified_n = modified_today.get(counselor, 0)
            created_m = created_monthly.get(counselor, 0)
            modified_m = modified_monthly.get(counselor, 0)
            metrics = task_metrics.get(counselor, {"task": 0, "overdues": 0, "no_task": 0})
            rows.append({
                "Date": day, "Counselor Name": counselor,
                "Created On_Day wise": created_n, "Created On (Monthly)": created_m,
                "Modified On (Daily)": modified_n, "Modified On (Monthly)": modified_m,
                "Modified %_Monthly": safe_pct(modified_m, created_m),
                "Overdues": metrics["overdues"], "Task": metrics["task"],
                "Overdues %": safe_pct(metrics["overdues"], metrics["task"]),
                "No Task": metrics["no_task"], "No Task %": safe_pct(metrics["no_task"], created_n),
                "is_total": False,
            })
        day_df = pd.DataFrame(rows)
        total_row = {col: "" for col in COLUMNS}
        total_row["Counselor Name"] = "Total"
        for col in _SUM_COLUMNS:
            total_row[col] = day_df[col].sum() if not day_df.empty else 0
        total_row["is_total"] = True
        day_rows[day] = rows + [total_row]

    df = order_newest_first(day_rows, COLUMNS)
    return ReportResult(
        key="lead_funnel", title="Lead Funnel",
        date_basis="Created date; Modified date; task due date", dataframe=df,
    )
