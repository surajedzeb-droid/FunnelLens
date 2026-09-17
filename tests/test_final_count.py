from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from funnellens.reports import ReportContext, ReportError
from funnellens.reports.final_count import build

from tests.fixtures.reports_fixture import DAY1, DAY2, RUN_AT, build_fixture_dataset
from tests.test_reports import make_settings


def make_fake_client(tasks_by_owner: dict) -> MagicMock:
    client = MagicMock()
    client.get_tasks_for_owner.side_effect = lambda owner_id: tasks_by_owner.get(owner_id, [])
    return client


def test_final_count_requires_a_client():
    context = ReportContext(settings=make_settings(), run_at=RUN_AT)  # no client
    with pytest.raises(ReportError, match="live LSQClient"):
        build(build_fixture_dataset(), DAY1, DAY2, context)


def test_final_count_one_row_per_active_counselor():
    client = make_fake_client({})
    context = ReportContext(settings=make_settings(), run_at=RUN_AT, client=client)
    result = build(build_fixture_dataset(), DAY1, DAY2, context)
    assert sorted(result.dataframe["Counselor Name"]) == ["Alice", "Bob"]


def test_final_count_created_and_enrolled_and_conversion_pct():
    client = make_fake_client({})
    context = ReportContext(settings=make_settings(), run_at=RUN_AT, client=client)
    result = build(build_fixture_dataset(), DAY1, DAY2, context)
    bob = result.dataframe[result.dataframe["Counselor Name"] == "Bob"].iloc[0]
    assert bob["Created On"] == 2       # L3, L5
    assert bob["Enrolled"] == 1         # L5
    assert bob["Conversion %"] == 50.0  # 1 / 2 * 100


def test_final_count_till_date_is_always_blank():
    client = make_fake_client({})
    context = ReportContext(settings=make_settings(), run_at=RUN_AT, client=client)
    result = build(build_fixture_dataset(), DAY1, DAY2, context)
    assert (result.dataframe["Till Date"] == "").all()


def test_final_count_no_task_monthly_equals_no_task_total():
    client = make_fake_client({})
    context = ReportContext(settings=make_settings(), run_at=RUN_AT, client=client)
    result = build(build_fixture_dataset(), DAY1, DAY2, context)
    df = result.dataframe
    assert (df["No Task_Monthly"] == df["No Task_Total"]).all()


def test_final_count_live_overdue_snapshot_uses_now_not_pull_time():
    overdue_task = {"DueDate": "2026-09-01 00:00:00.000", "Status": "Pending"}
    future_task = {"DueDate": "2026-09-30 00:00:00.000", "Status": "Pending"}
    client = make_fake_client({"a1": [overdue_task, future_task], "b1": []})
    context = ReportContext(settings=make_settings(), run_at=RUN_AT, client=client)
    result = build(build_fixture_dataset(), DAY1, DAY2, context)
    alice = result.dataframe[result.dataframe["Counselor Name"] == "Alice"].iloc[0]
    assert alice["Overdues_Total"] == 1       # only the already-due task, not the future one
    assert alice["Overdues_Monthly"] == 1     # both fall in RUN_AT's month (September)


def test_final_count_referral_and_direct_walk_in_columns():
    client = make_fake_client({})
    context = ReportContext(settings=make_settings(), run_at=RUN_AT, client=client)
    result = build(build_fixture_dataset(), DAY1, DAY2, context)
    bob = result.dataframe[result.dataframe["Counselor Name"] == "Bob"].iloc[0]
    assert bob["Referral (This Month)"] == 2  # L3, L5 both source=Referral
    alice = result.dataframe[result.dataframe["Counselor Name"] == "Alice"].iloc[0]
    assert alice["Direct Walk In (This Month)"] == 0
