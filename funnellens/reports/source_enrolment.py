"""Source Wise Enrolment report: one row per active counselor per month, Enrolled and
Conversion %% by Source (LOGIC_SPEC.md section 3.7). Scoped to `to_date`'s calendar month,
matching Final Count's month scoping (LOGIC_SPEC.md section 3.6). P_Source on the
enrolment search is unreliable (LOGIC_SPEC.md section 2), so Source is looked up via the
lead itself instead."""

from __future__ import annotations

from datetime import date

import pandas as pd

from funnellens.extract import Dataset
from funnellens.reports import ReportContext, ReportResult
from funnellens.reports._shared import active_counselor_names, safe_pct


def _source_order(created: pd.DataFrame, month_start: date, to_date: date) -> list[str]:
    if created.empty:
        return []
    window = created[(created["ist_date"] >= month_start) & (created["ist_date"] <= to_date)].sort_values("ist_date")
    ordered, seen = [], set()
    for value in window["source"]:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    if "(Blank)" in ordered:
        ordered.remove("(Blank)")
        ordered.append("(Blank)")
    return ordered


def build(dataset: Dataset, from_date: date, to_date: date, context: ReportContext) -> ReportResult:
    month_start = to_date.replace(day=1)
    counselors = active_counselor_names(dataset)
    created = dataset.leads_created
    enrolments = dataset.enrolments
    sources = _source_order(created, month_start, to_date)

    columns = ["Date", "Counselor Name"]
    for source in sources:
        columns += [f"{source} Enrolled", f"{source} Conversion %"]

    lead_source = created.drop_duplicates("lead_id").set_index("lead_id")["source"] if not created.empty else pd.Series(dtype=str)
    created_window = created[(created["ist_date"] >= month_start) & (created["ist_date"] <= to_date)] if not created.empty else created
    created_by_source_counselor = (created_window.groupby(["counselor_name", "source"]).size()
                                    if not created_window.empty else pd.Series(dtype=int))

    if not enrolments.empty and "ist_date" in enrolments.columns:
        month_enrolments = enrolments[(enrolments["ist_date"] >= month_start) & (enrolments["ist_date"] <= to_date)].copy()
        month_enrolments["source"] = month_enrolments["lead_id"].map(lead_source)
        enrolled_by_source_counselor = (month_enrolments.groupby(["counselor_name", "source"]).size()
                                         if not month_enrolments.empty else pd.Series(dtype=int))
    else:
        enrolled_by_source_counselor = pd.Series(dtype=int)

    rows = []
    for counselor in counselors:
        row = {"Date": "", "Counselor Name": counselor}
        for source in sources:
            enrolled_n = int(enrolled_by_source_counselor.get((counselor, source), 0))
            created_n = int(created_by_source_counselor.get((counselor, source), 0))
            row[f"{source} Enrolled"] = enrolled_n
            row[f"{source} Conversion %"] = safe_pct(enrolled_n, created_n)
        row["is_total"] = False
        rows.append(row)

    df = pd.DataFrame(rows, columns=[*columns, "is_total"])
    return ReportResult(key="source_enrolment", title="Source Wise Enrolment",
                         date_basis="Enrolled Date (month of to_date)", dataframe=df)
