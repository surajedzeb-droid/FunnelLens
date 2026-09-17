from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from funnellens import pipeline
from funnellens.extract import Dataset
from funnellens.filters import Rule
from funnellens.pipeline import PipelineError, PipelineOptions, run_pipeline
from funnellens.settings import Secrets, Settings

DAY = date(2026, 9, 15)


def make_settings() -> Settings:
    return Settings(
        secrets=Secrets(access_key="a", secret_key="b", api_host="h"),
        config={
            "timezone": "Asia/Kolkata",
            "fields": {"lead_id": "ProspectID", "owner_id": "OwnerId", "owner_name": "OwnerIdName",
                       "created_on": "CreatedOn", "modified_on": "ModifiedOn", "source": "Source",
                       "course": "mx_Enquired_Course", "opportunity_stage": "mx_Custom_2",
                       "opportunity_status": "Status", "enrolled_date": "mx_Custom_45",
                       "task_due_date": "DueDate", "task_status": "Status"},
            "stages": ["Hot", "Cold"], "excluded_owner_roles": [], "excluded_owner_names": ["Bad Actor"],
            "opportunity_event_code": 12000,
            "api": {"page_size": 1000, "opportunity_search_page_size": 200, "max_records": 100000,
                    "max_opportunity_search_records": 4000, "max_workers": 3, "retry_attempts": 3},
        },
    )


def make_fake_client() -> MagicMock:
    client = MagicMock()
    client.run_parallel.side_effect = lambda calls: [c() for c in calls]
    client.search_leads_created_between.return_value = [
        {"ProspectID": "1", "OwnerId": "o1", "OwnerIdName": "Alice", "CreatedOn": "2026-09-15 05:00:00",
         "ModifiedOn": "2026-09-15 05:00:00", "Source": "Web", "mx_Enquired_Course": "ACCA"},
    ]
    client.search_leads_modified_between.return_value = []
    client.search_opportunities_by_enrolled_date.return_value = []
    client.get_opportunities_of_lead.return_value = None
    client.get_tasks_for_lead.return_value = []
    client.get_tasks_for_owner.return_value = []
    client.get_users.return_value = [
        {"ID": "o1", "FirstName": "Alice", "LastName": "", "StatusCode": 0, "Role": "Counselor"},
        {"ID": "o2", "FirstName": "Bad", "LastName": "Actor", "StatusCode": 0, "Role": "Counselor"},
    ]
    client.call_count = 7
    return client


@pytest.fixture(autouse=True)
def patch_settings_and_client(monkeypatch, tmp_path):
    from funnellens import cache
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(pipeline, "load_settings", lambda: make_settings())
    monkeypatch.setattr(pipeline, "LSQClient", lambda settings: make_fake_client())
    monkeypatch.setattr(pipeline, "OUTPUT_DIR", tmp_path / "output")


def make_options(**overrides) -> PipelineOptions:
    defaults = dict(from_date=DAY, to_date=DAY, report_keys=["lead_funnel"])
    defaults.update(overrides)
    return PipelineOptions(**defaults)


def test_run_pipeline_returns_bytes_and_run_info():
    data, run_info = run_pipeline(make_options())
    assert isinstance(data, bytes)
    assert run_info["from_date"] == DAY
    assert run_info["api_calls"] == 7
    assert "output_path" in run_info
    assert run_info["issues"] == []


def test_run_pipeline_rejects_unknown_report_key():
    with pytest.raises(PipelineError, match="Unknown report key"):
        run_pipeline(make_options(report_keys=["not_a_real_report"]))


def test_run_pipeline_rejects_reversed_date_range():
    with pytest.raises(PipelineError, match="before"):
        run_pipeline(make_options(from_date=date(2026, 9, 16), to_date=date(2026, 9, 15)))


def test_run_pipeline_always_includes_raw_sheet(tmp_path):
    _, run_info = run_pipeline(make_options(out_path=tmp_path / "out.xlsx"))
    import openpyxl
    wb = openpyxl.load_workbook(tmp_path / "out.xlsx")
    assert "Raw Data" in wb.sheetnames


def test_run_pipeline_excludes_owners_by_default(tmp_path):
    # "Bad Actor" is on excluded_owner_names in make_settings(); Alice created the only lead.
    data, run_info = run_pipeline(make_options(out_path=tmp_path / "out.xlsx"))
    assert run_info["row_counts"]["leads_created"] == 1  # Alice's lead survives; no excluded-owner lead in fixture


def test_run_pipeline_applies_extra_filters(tmp_path):
    options = make_options(filters=[Rule("source", "equals", "Web")], out_path=tmp_path / "out.xlsx")
    _, run_info = run_pipeline(options)
    assert run_info["filters"] == ["source equals Web"]


def test_run_pipeline_writes_to_default_path_when_not_given(tmp_path):
    _, run_info = run_pipeline(make_options())
    assert run_info["output_path"] == str(tmp_path / "output" / f"FunnelLens_{DAY}_to_{DAY}.xlsx")
