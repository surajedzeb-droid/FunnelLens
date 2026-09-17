from datetime import date

import pandas as pd
import pytest

from funnellens.reports import ReportContext
from funnellens.reports.course_wise import build as build_course
from funnellens.reports.lead_funnel import build as build_lead_funnel
from funnellens.reports.raw import build as build_raw
from funnellens.reports.reports_tab import build as build_reports
from funnellens.reports.source_enrolment import build as build_source_enrolment
from funnellens.reports.source_wise import build as build_source
from funnellens.reports.stage_wise import build as build_stage
from funnellens.settings import Secrets, Settings

from tests.fixtures.reports_fixture import DAY1, DAY2, RUN_AT, build_fixture_dataset

STAGES = [
    "Budget Issue", "Cold", "Connected", "Disqualified", "Enrolled", "Future Prospect", "Hot",
    "Interested", "Language Barrier", "Lost to Competitor", "New", "Not Reachable",
    "Offline in another city", "Reachable", "Warm",
]


def make_settings() -> Settings:
    return Settings(
        secrets=Secrets(access_key="a", secret_key="b", api_host="h"),
        config={
            "timezone": "Asia/Kolkata",
            "fields": {"opportunity_stage": "mx_Custom_2", "opportunity_status": "Status",
                       "source": "Source", "enrolled_date": "mx_Custom_45"},
            "stages": STAGES, "excluded_owner_roles": [], "excluded_owner_names": [],
            "opportunity_event_code": 12000,
            "api": {"page_size": 1000, "opportunity_search_page_size": 200, "max_records": 100000,
                    "max_opportunity_search_records": 4000, "max_workers": 3, "retry_attempts": 3},
        },
    )


def make_context() -> ReportContext:
    return ReportContext(settings=make_settings(), run_at=RUN_AT)


def row(df: pd.DataFrame, date_: date, counselor: str) -> pd.Series:
    match = df[(df["Date"] == date_) & (df["Counselor Name"] == counselor)]
    assert len(match) == 1, f"expected exactly one row for {counselor} on {date_}, got {len(match)}"
    return match.iloc[0]


def total_row(df: pd.DataFrame, date_: date) -> pd.Series:
    """The Total row for `date_` immediately follows that day's last counselor row --
    the Total row's own Date cell is blank, per LOGIC_SPEC.md."""
    day_indices = df.index[df["Date"] == date_].tolist()
    assert day_indices, f"no rows found for {date_}"
    total = df.loc[day_indices[-1] + 1]
    assert bool(total["is_total"])
    return total


# ---- Lead Funnel -------------------------------------------------------------

def test_lead_funnel_day1_counts():
    result = build_lead_funnel(build_fixture_dataset(), DAY1, DAY2, make_context())
    df = result.dataframe
    alice = row(df, DAY1, "Alice")
    assert alice["Created On_Day wise"] == 2
    assert alice["Modified On (Daily)"] == 1
    assert alice["Created On (Monthly)"] == 2
    assert alice["Modified On (Monthly)"] == 1
    assert alice["Modified %_Monthly"] == 50.0
    assert alice["Task"] == 3       # L1 (2 tasks) + L2 (1 task)
    assert alice["Overdues"] == 2   # both Pending tasks due before RUN_AT
    assert alice["No Task"] == 0

    bob = row(df, DAY1, "Bob")
    assert bob["Created On_Day wise"] == 1
    assert bob["Task"] == 0
    assert bob["No Task"] == 1
    assert bob["No Task %"] == 100.0


def test_lead_funnel_day2_monthly_rollup_accumulates():
    result = build_lead_funnel(build_fixture_dataset(), DAY1, DAY2, make_context())
    df = result.dataframe
    alice = row(df, DAY2, "Alice")
    assert alice["Created On_Day wise"] == 1
    assert alice["Created On (Monthly)"] == 3   # 2 (day1) + 1 (day2)
    assert alice["Modified On (Monthly)"] == 2  # 1 (day1) + 1 (day2)
    assert alice["Task"] == 1
    assert alice["Overdues"] == 0  # L4's task is due after RUN_AT


def test_lead_funnel_total_row_sums_the_day_block():
    result = build_lead_funnel(build_fixture_dataset(), DAY1, DAY2, make_context())
    total = total_row(result.dataframe, DAY1)
    assert total["Created On_Day wise"] == 3
    assert total["Modified On (Daily)"] == 1
    assert total["Overdues"] == 2
    assert total["Task"] == 3
    assert total["No Task"] == 1
    assert total["Created On (Monthly)"] == ""  # blank on the Total row, per LOGIC_SPEC.md


def test_lead_funnel_days_are_newest_first():
    result = build_lead_funnel(build_fixture_dataset(), DAY1, DAY2, make_context())
    dates = result.dataframe["Date"].tolist()
    assert dates.index(DAY2) < dates.index(DAY1)


# ---- Stage Wise ----------------------------------------------------------------

def test_stage_wise_counts_and_not_modified():
    result = build_stage(build_fixture_dataset(), DAY1, DAY2, make_context())
    df = result.dataframe
    alice_day1 = row(df, DAY1, "Alice")
    assert alice_day1["Hot"] == 1          # L1
    assert alice_day1["Not Reachable"] == 1  # L2
    assert alice_day1["Not Modified"] == 0
    assert alice_day1["Total"] == 2

    alice_day2 = row(df, DAY2, "Alice")
    assert alice_day2["Not Modified"] == 1  # L4 has no opportunity row
    assert alice_day2["Total"] == 1


def test_stage_wise_has_stage_as_of_label():
    result = build_stage(build_fixture_dataset(), DAY1, DAY2, make_context())
    assert result.stage_basis_label == "Stage as of 2026-09-03"


def test_stage_wise_blank_spacer_column_present():
    result = build_stage(build_fixture_dataset(), DAY1, DAY2, make_context())
    assert "" in result.dataframe.columns


# ---- Source Wise / Course Wise (dynamic pivot) ----------------------------------

def test_source_wise_dynamic_columns_and_blank_last():
    result = build_source(build_fixture_dataset(), DAY1, DAY2, make_context())
    df = result.dataframe
    cols = list(df.columns)
    assert "Web" in cols and "Referrals" in cols and "Total" in cols
    assert cols.index("Total") == len(cols) - 2  # last before is_total
    alice_day1 = row(df, DAY1, "Alice")
    assert alice_day1["Web"] == 2
    assert alice_day1["Total"] == 2


def test_course_wise_uses_course_field():
    result = build_course(build_fixture_dataset(), DAY1, DAY2, make_context())
    df = result.dataframe
    assert "ACCA" in df.columns and "CMA" in df.columns
    alice_day1 = row(df, DAY1, "Alice")
    assert alice_day1["ACCA"] == 2


# ---- Reports tab ----------------------------------------------------------------

def test_reports_tab_lost_and_nr_today():
    result = build_reports(build_fixture_dataset(), DAY1, DAY2, make_context())
    df = result.dataframe
    bob_day2 = row(df, DAY2, "Bob")
    assert bob_day2["Lost Today"] == 1     # L3 modified day2, status Lost
    alice_day2 = row(df, DAY2, "Alice")
    assert alice_day2["NR Today"] == 1     # L2 modified day2, stage Not Reachable


def test_reports_tab_enrolled_uses_enrolments_not_modified_leads():
    result = build_reports(build_fixture_dataset(), DAY1, DAY2, make_context())
    df = result.dataframe
    bob_day2 = row(df, DAY2, "Bob")
    assert bob_day2["Enrolled Today"] == 1
    alice_day2 = row(df, DAY2, "Alice")
    assert alice_day2["Enrolled Today"] == 0


def test_reports_tab_yesterday_matches_prior_day_new_today():
    result = build_reports(build_fixture_dataset(), DAY1, DAY2, make_context())
    df = result.dataframe
    alice_day2 = row(df, DAY2, "Alice")
    assert alice_day2["Total Yesterday"] == 2  # Alice's "New Today" on DAY1 was 2


# ---- Source Wise Enrolment --------------------------------------------------------

def test_source_enrolment_one_row_per_active_counselor():
    result = build_source_enrolment(build_fixture_dataset(), DAY1, DAY2, make_context())
    df = result.dataframe
    assert sorted(df["Counselor Name"]) == ["Alice", "Bob"]


def test_source_enrolment_conversion_pct_for_referral():
    result = build_source_enrolment(build_fixture_dataset(), DAY1, DAY2, make_context())
    df = result.dataframe
    bob = df[df["Counselor Name"] == "Bob"].iloc[0]
    assert bob["Referrals Enrolled"] == 1
    assert bob["Referrals Conversion %"] == 50.0  # 1 enrolled / 2 created (L3, L5) this month


# ---- Raw Data -----------------------------------------------------------------

def test_raw_data_includes_created_and_modified_rows_with_basis_column():
    result = build_raw(build_fixture_dataset(), DAY1, DAY2, make_context())
    df = result.dataframe
    assert set(df["basis"]) == {"created", "modified"}
    assert (df["lead_id"] == "L1").any()


def test_raw_data_mask_pii_is_a_safe_noop_when_no_pii_columns_exist():
    context = ReportContext(settings=make_settings(), run_at=RUN_AT, mask_pii=True)
    result = build_raw(build_fixture_dataset(), DAY1, DAY2, context)
    assert not result.dataframe.empty
