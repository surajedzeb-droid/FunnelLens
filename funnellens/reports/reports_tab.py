"""Reports tab: Lost, Not Reachable and Enrolled counts, daily and monthly
(LOGIC_SPEC.md section 3.5). Enrolled comes from the enrolments DataFrame (Opportunity
Advanced Search by Enrolled Date), never from modified-date leads (README Critical Rule 5).
"NR Yesterday %"'s denominator is "Total Yesterday" (not an NR-specific total) -- coded
exactly as the Apps Script does it, for verification against the Sheet (Resolved Decision 15).
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from funnellens.extract import Dataset
from funnellens.reports import ReportContext, ReportResult
from funnellens.reports._shared import active_counselor_names, day_count, month_to_date_count, order_newest_first, safe_pct

COLUMNS = [
    "Date", "Counselor Name", "New Today", "Total Yesterday", "Lost Yesterday", "Lost Yesterday %",
    "Lost Today", "Lost Today %", "NR Yesterday", "NR Yesterday %", "NR Today", "NR Today %",
    "Total This Month", "Lost This Month", "Lost This Month %", "NR This Month", "NR This Month %",
    "Enrolled Today", "Enrolled This Month",
]
_SUM_COLUMNS = {"New Today", "Lost Today", "NR Today", "Enrolled Today"}


def _status_matches(series: pd.Series, target: str) -> pd.Series:
    return series.astype(str).str.strip().str.lower() == target.lower()


def _tagged_modified(modified: pd.DataFrame, day: date, status_by_lead: pd.Series, stage_by_lead: pd.Series) -> pd.DataFrame:
    if modified.empty:
        return modified
    day_leads = modified[modified["ist_date"] == day].copy()
    if day_leads.empty:
        return day_leads
    day_leads["opportunity_status"] = day_leads["lead_id"].map(status_by_lead)
    day_leads["opportunity_stage"] = day_leads["lead_id"].map(stage_by_lead)
    return day_leads


def build(dataset: Dataset, from_date: date, to_date: date, context: ReportContext) -> ReportResult:
    created = dataset.leads_created
    modified = dataset.leads_modified
    opportunities = dataset.opportunities
    enrolments = dataset.enrolments
    counselors = active_counselor_names(dataset)
    days = [from_date + timedelta(days=i) for i in range((to_date - from_date).days + 1)]

    status_by_lead = (opportunities.set_index("lead_id")["opportunity_status"]
                       if not opportunities.empty and "opportunity_status" in opportunities.columns else pd.Series(dtype=str))
    stage_by_lead = (opportunities.set_index("lead_id")["opportunity_stage"]
                      if not opportunities.empty and "opportunity_stage" in opportunities.columns else pd.Series(dtype=str))

    daily_new = created[["ist_date", "counselor_name"]] if not created.empty else pd.DataFrame(columns=["ist_date", "counselor_name"])
    lost_rows, nr_rows = [], []
    # Every day whose Yesterday/Monthly window could matter -- one extra day before from_date.
    scan_days = [from_date - timedelta(days=1) + timedelta(days=i)
                 for i in range((to_date - from_date).days + 2)]
    for day in scan_days:
        tagged = _tagged_modified(modified, day, status_by_lead, stage_by_lead)
        if tagged.empty:
            continue
        for counselor in tagged.loc[_status_matches(tagged["opportunity_status"], "Lost"), "counselor_name"]:
            lost_rows.append({"ist_date": day, "counselor_name": counselor})
        for counselor in tagged.loc[_status_matches(tagged["opportunity_stage"], "Not Reachable"), "counselor_name"]:
            nr_rows.append({"ist_date": day, "counselor_name": counselor})
    daily_lost = pd.DataFrame(lost_rows, columns=["ist_date", "counselor_name"])
    daily_nr = pd.DataFrame(nr_rows, columns=["ist_date", "counselor_name"])
    daily_enrolled = (enrolments[["ist_date", "counselor_name"]]
                      if not enrolments.empty and "ist_date" in enrolments.columns
                      else pd.DataFrame(columns=["ist_date", "counselor_name"]))

    day_rows: dict[date, list[dict]] = {}
    for day in days:
        yesterday = day - timedelta(days=1)
        new_today = day_count(daily_new, "ist_date", "counselor_name", day)
        lost_today = day_count(daily_lost, "ist_date", "counselor_name", day)
        nr_today = day_count(daily_nr, "ist_date", "counselor_name", day)
        enrolled_today = day_count(daily_enrolled, "ist_date", "counselor_name", day)
        total_yesterday = day_count(daily_new, "ist_date", "counselor_name", yesterday)
        lost_yesterday = day_count(daily_lost, "ist_date", "counselor_name", yesterday)
        nr_yesterday = day_count(daily_nr, "ist_date", "counselor_name", yesterday)
        total_month = month_to_date_count(daily_new, "ist_date", "counselor_name", day)
        lost_month = month_to_date_count(daily_lost, "ist_date", "counselor_name", day)
        nr_month = month_to_date_count(daily_nr, "ist_date", "counselor_name", day)
        enrolled_month = month_to_date_count(daily_enrolled, "ist_date", "counselor_name", day)
        modified_today = day_count(modified, "ist_date", "counselor_name", day)

        rows = []
        for counselor in counselors:
            new_n, lost_n, nr_n, enrolled_n = (new_today.get(counselor, 0), lost_today.get(counselor, 0),
                                                nr_today.get(counselor, 0), enrolled_today.get(counselor, 0))
            total_y, lost_y, nr_y = (total_yesterday.get(counselor, 0), lost_yesterday.get(counselor, 0),
                                      nr_yesterday.get(counselor, 0))
            total_m, lost_m, nr_m, enrolled_m = (total_month.get(counselor, 0), lost_month.get(counselor, 0),
                                                  nr_month.get(counselor, 0), enrolled_month.get(counselor, 0))
            modified_n = modified_today.get(counselor, 0)
            rows.append({
                "Date": day, "Counselor Name": counselor,
                "New Today": new_n, "Total Yesterday": total_y,
                "Lost Yesterday": lost_y, "Lost Yesterday %": safe_pct(lost_y, total_y),
                "Lost Today": lost_n, "Lost Today %": safe_pct(lost_n, modified_n),
                "NR Yesterday": nr_y, "NR Yesterday %": safe_pct(nr_y, total_y),
                "NR Today": nr_n, "NR Today %": safe_pct(nr_n, modified_n),
                "Total This Month": total_m, "Lost This Month": lost_m, "Lost This Month %": safe_pct(lost_m, total_m),
                "NR This Month": nr_m, "NR This Month %": safe_pct(nr_m, total_m),
                "Enrolled Today": enrolled_n, "Enrolled This Month": enrolled_m,
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
    return ReportResult(key="reports", title="Reports",
                         date_basis="Created date (New), Modified date (Lost/NR), Enrolled date (Enrolled)",
                         dataframe=df)
