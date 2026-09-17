from unittest.mock import MagicMock

from funnellens.checks import (
    check_no_blank_named_columns,
    check_no_duplicate_counselors,
    check_no_suspicious_round_numbers,
    check_total_rows_match_their_block,
    run_checks,
)
from funnellens.reports import ReportContext
from funnellens.reports.final_count import build as build_final
from funnellens.reports.lead_funnel import build as build_lead_funnel
from funnellens.reports.stage_wise import build as build_stage

from tests.fixtures.reports_fixture import DAY1, DAY2, RUN_AT, build_fixture_dataset
from tests.test_reports import make_settings


def make_context(client=None) -> ReportContext:
    return ReportContext(settings=make_settings(), run_at=RUN_AT, client=client)


def test_check_total_rows_match_their_block_passes_on_correct_report():
    result = build_lead_funnel(build_fixture_dataset(), DAY1, DAY2, make_context())
    assert check_total_rows_match_their_block(result) == []


def test_check_total_rows_match_their_block_catches_a_broken_total():
    result = build_lead_funnel(build_fixture_dataset(), DAY1, DAY2, make_context())
    df = result.dataframe.copy()
    total_idx = df.index[df["is_total"]][0]
    df.loc[total_idx, "Created On_Day wise"] = 999
    result.dataframe = df
    issues = check_total_rows_match_their_block(result)
    assert any("Created On_Day wise" in issue for issue in issues)


def test_check_no_duplicate_counselors_passes_on_correct_final_count():
    client = MagicMock()
    client.get_tasks_for_owner.return_value = []
    result = build_final(build_fixture_dataset(), DAY1, DAY2, make_context(client))
    assert check_no_duplicate_counselors(result) == []


def test_check_no_duplicate_counselors_catches_a_duplicate_row():
    client = MagicMock()
    client.get_tasks_for_owner.return_value = []
    result = build_final(build_fixture_dataset(), DAY1, DAY2, make_context(client))
    result.dataframe = result.dataframe._append(result.dataframe.iloc[0], ignore_index=True)
    issues = check_no_duplicate_counselors(result)
    assert len(issues) == 1


def test_check_no_blank_named_columns_allows_stage_wise_spacer():
    result = build_stage(build_fixture_dataset(), DAY1, DAY2, make_context())
    assert check_no_blank_named_columns(result) == []


def test_check_no_suspicious_round_numbers_flags_exact_cap_values():
    result = build_lead_funnel(build_fixture_dataset(), DAY1, DAY2, make_context())
    df = result.dataframe.copy()
    df.loc[0, "Task"] = 500
    result.dataframe = df
    issues = check_no_suspicious_round_numbers(result)
    assert any("500" in issue for issue in issues)


def test_run_checks_on_a_correct_set_of_reports_reports_no_created_mismatch():
    client = MagicMock()
    client.get_tasks_for_owner.return_value = []
    context = make_context(client)
    dataset = build_fixture_dataset()
    results = {
        "lead_funnel": build_lead_funnel(dataset, DAY1, DAY2, context),
        "stage": build_stage(dataset, DAY1, DAY2, context),
    }
    issues = run_checks(results)
    assert not any("Created total mismatch" in issue for issue in issues)
