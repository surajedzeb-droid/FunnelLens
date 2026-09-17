"""Report registry: maps report keys to builder functions and display names (Phase 4).

Every builder has the signature build(dataset, from_date, to_date, context) -> ReportResult.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

import pandas as pd

from funnellens.extract import Dataset
from funnellens.lsq_client import LSQClient
from funnellens.settings import Settings
from funnellens.timeutil import IST


class ReportError(Exception):
    """Raised when a report can't be built -- e.g. it needs a live LSQClient that wasn't given."""


@dataclass
class ReportContext:
    settings: Settings
    run_at: datetime  # exact instant reports are generated -- drives overdue-vs-now comparisons
    # (LOGIC_SPEC.md 6.1-6.2) and the stage-as-of label. Only final_count.py needs `client`,
    # for its live Overdues snapshot (LOGIC_SPEC.md 6.1) -- every other report is a pure
    # function of `dataset`.
    client: LSQClient | None = None
    mask_pii: bool = False

    @property
    def run_date(self) -> date:
        return self.run_at.astimezone(IST).date()


@dataclass
class ReportResult:
    key: str
    title: str
    date_basis: str
    dataframe: pd.DataFrame  # includes a boolean "is_total" column marking Total rows
    stage_basis_label: str | None = None


BuilderFn = Callable[[Dataset, date, date, ReportContext], ReportResult]

from funnellens.reports.course_wise import build as _build_course
from funnellens.reports.final_count import build as _build_final
from funnellens.reports.lead_funnel import build as _build_lead_funnel
from funnellens.reports.raw import build as _build_raw
from funnellens.reports.reports_tab import build as _build_reports
from funnellens.reports.source_enrolment import build as _build_source_enrolment
from funnellens.reports.source_wise import build as _build_source
from funnellens.reports.stage_wise import build as _build_stage

REGISTRY: dict[str, tuple[BuilderFn, str]] = {
    "lead_funnel": (_build_lead_funnel, "Lead Funnel"),
    "stage": (_build_stage, "Stage Wise"),
    "source": (_build_source, "Source Wise"),
    "course": (_build_course, "Course Wise"),
    "reports": (_build_reports, "Reports"),
    "final": (_build_final, "Final Count"),
    "source_enrolment": (_build_source_enrolment, "Source Wise Enrolment"),
    "raw": (_build_raw, "Raw Data"),
}
