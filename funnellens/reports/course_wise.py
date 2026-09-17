"""Course Wise report: identical mechanism to Source Wise, keyed by course instead of
source (LOGIC_SPEC.md section 3.4)."""

from __future__ import annotations

from datetime import date

from funnellens.extract import Dataset
from funnellens.reports import ReportContext, ReportResult
from funnellens.reports._shared import build_dynamic_pivot_report


def build(dataset: Dataset, from_date: date, to_date: date, context: ReportContext) -> ReportResult:
    df = build_dynamic_pivot_report(dataset, from_date, to_date, "course")
    return ReportResult(key="course", title="Course Wise", date_basis="Lead created date", dataframe=df)
