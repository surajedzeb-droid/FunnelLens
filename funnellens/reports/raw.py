"""Raw Data report: one traceable row per lead (created or modified in range), with the
underlying fields every other report's totals are built from -- replaces the Apps Script's
Master Data tab for tracing numbers back to source leads (README section 7). Not itself
specified column-by-column in docs/LOGIC_SPEC.md.

mask_pii redacts any phone/email-like columns if present. Phase 2 doesn't currently fetch
such fields (LOGIC_SPEC.md never documents them for this LeadSquared account), so this is
a no-op today rather than inventing an unconfirmed field name."""

from __future__ import annotations

from datetime import date

import pandas as pd

from funnellens.extract import Dataset
from funnellens.reports import ReportContext, ReportResult

_PII_COLUMNS = ("phone", "email", "email_address", "mobile")


def build(dataset: Dataset, from_date: date, to_date: date, context: ReportContext) -> ReportResult:
    created, modified, opportunities = dataset.leads_created, dataset.leads_modified, dataset.opportunities

    frames = []
    if not created.empty:
        c = created[(created["ist_date"] >= from_date) & (created["ist_date"] <= to_date)].copy()
        c["basis"] = "created"
        frames.append(c)
    if not modified.empty:
        m = modified[(modified["ist_date"] >= from_date) & (modified["ist_date"] <= to_date)].copy()
        m["basis"] = "modified"
        frames.append(m)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    if not combined.empty and not opportunities.empty:
        combined = combined.merge(opportunities, on="lead_id", how="left", suffixes=("", "_opportunity"))

    if context.mask_pii:
        for col in combined.columns:
            if col.lower() in _PII_COLUMNS:
                combined[col] = "***"

    combined["is_total"] = False
    return ReportResult(key="raw", title="Raw Data", date_basis="Created date and Modified date", dataframe=combined)
