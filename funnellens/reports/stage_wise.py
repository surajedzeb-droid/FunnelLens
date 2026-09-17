"""Stage Wise report: day x stage counts, one row per active counselor per day
(LOGIC_SPEC.md section 3.2). Despite the Apps Script tab's "...Modified On..." name, the
logic is Created-date based (Resolved Decision 7 in LOGIC_SPEC.md).

Stage-based counts are only ever as fresh as "now" (LeadSquared returns a lead's current
stage, not its stage on a past date -- README section 7.1), so every row carries a
"Stage as of <run date>" label. From Phase 9 on, a daily snapshot lets past days use the
stage as it was on that date instead; there is no hook for that here yet since Phase 9
hasn't landed."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from funnellens.extract import Dataset
from funnellens.reports import ReportContext, ReportResult
from funnellens.reports._shared import active_counselor_names, order_newest_first, safe_pct


def build(dataset: Dataset, from_date: date, to_date: date, context: ReportContext) -> ReportResult:
    stages = context.settings.stages
    stage_lookup = {s.strip().lower(): s for s in stages}
    columns = ["Date", "Counselor Name", *stages, "Not Modified", "", "Total", "Disqualified %", "Enrolled %"]
    sum_columns = {*stages, "Not Modified", "Total"}

    created = dataset.leads_created
    opportunities = dataset.opportunities
    counselors = active_counselor_names(dataset)
    days = [from_date + timedelta(days=i) for i in range((to_date - from_date).days + 1)]

    stage_by_lead = (opportunities.set_index("lead_id")["opportunity_stage"]
                      if not opportunities.empty and "opportunity_stage" in opportunities.columns
                      else pd.Series(dtype=str))

    day_rows: dict[date, list[dict]] = {}
    for day in days:
        day_leads = created[created["ist_date"] == day] if not created.empty else created
        rows = []
        for counselor in counselors:
            counselor_leads = (day_leads[day_leads["counselor_name"] == counselor]
                                if not day_leads.empty else day_leads)
            counts = {s: 0 for s in stages}
            not_modified = 0
            for lead_id in counselor_leads.get("lead_id", []):
                raw_stage = stage_by_lead.get(lead_id)
                matched = stage_lookup.get(str(raw_stage).strip().lower()) if pd.notna(raw_stage) else None
                if matched:
                    counts[matched] += 1
                else:
                    not_modified += 1
            total = sum(counts.values()) + not_modified
            row = {"Date": day, "Counselor Name": counselor, **counts, "Not Modified": not_modified, "": "",
                   "Total": total, "Disqualified %": safe_pct(counts.get("Disqualified", 0), total),
                   "Enrolled %": safe_pct(counts.get("Enrolled", 0), total), "is_total": False}
            rows.append(row)

        day_df = pd.DataFrame(rows)
        total_row = {col: "" for col in columns}
        total_row["Counselor Name"] = "Total"
        for col in sum_columns:
            total_row[col] = day_df[col].sum() if not day_df.empty else 0
        total_row["Disqualified %"] = safe_pct(total_row.get("Disqualified", 0), total_row["Total"])
        total_row["Enrolled %"] = safe_pct(total_row.get("Enrolled", 0), total_row["Total"])
        total_row["is_total"] = True
        day_rows[day] = rows + [total_row]

    df = order_newest_first(day_rows, columns)
    return ReportResult(
        key="stage", title="Stage Wise", date_basis="Lead created date", dataframe=df,
        stage_basis_label=f"Stage as of {context.run_date.isoformat()}",
    )
