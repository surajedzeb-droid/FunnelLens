import pandas as pd

from funnellens.normalize import (
    build_counselor_roster,
    canonicalize_column,
    normalize_leads,
    normalize_opportunities,
)
from funnellens.settings import Secrets, Settings


def make_settings(**overrides) -> Settings:
    config = {
        "timezone": "Asia/Kolkata",
        "fields": {
            "lead_id": "ProspectID", "owner_id": "OwnerId", "owner_name": "OwnerIdName",
            "created_on": "CreatedOn", "modified_on": "ModifiedOn", "source": "Source",
            "course": "mx_Enquired_Course", "opportunity_stage": "mx_Custom_2",
            "opportunity_status": "Status", "enrolled_date": "mx_Custom_45",
            "task_due_date": "DueDate", "task_status": "Status",
        },
        "stages": [], "excluded_owner_roles": ["Administrator"], "excluded_owner_names": ["Bad Actor"],
        "opportunity_event_code": 12000,
        "api": {"page_size": 1000, "opportunity_search_page_size": 200, "max_records": 100000,
                "max_opportunity_search_records": 4000, "max_workers": 3, "retry_attempts": 3},
    }
    config.update(overrides)
    return Settings(secrets=Secrets(access_key="a", secret_key="b", api_host="h"), config=config)


def test_canonicalize_column_merges_case_and_whitespace_variants():
    series = pd.Series(["ACCA", "acca ", " Acca", "ACCA"])
    result = canonicalize_column(series)
    assert result.nunique() == 1
    assert result.iloc[0] == "ACCA"  # most common original spelling wins


def test_canonicalize_column_blank_and_missing_become_blank_marker():
    series = pd.Series(["", "   ", None, "nan"])
    result = canonicalize_column(series)
    assert (result == "(Blank)").all()


def test_build_counselor_roster_flags_excluded_role_and_name():
    users = pd.DataFrame([
        {"ID": "u1", "FirstName": "Anuj", "LastName": "Thakur", "StatusCode": 0, "Role": "Counselor"},
        {"ID": "u2", "FirstName": "Bad", "LastName": "Actor", "StatusCode": 0, "Role": "Counselor"},
        {"ID": "u3", "FirstName": "Admin", "LastName": "", "StatusCode": 0, "Role": "Administrator"},
    ])
    roster = build_counselor_roster(users, make_settings())
    by_id = roster.set_index("owner_id")
    assert by_id.loc["u1", "counselor_name"] == "Anuj Thakur"
    assert by_id.loc["u1", "is_excluded_owner"] == False
    assert by_id.loc["u2", "is_excluded_owner"] == True  # excluded by name
    assert by_id.loc["u3", "is_excluded_owner"] == True  # excluded by role


def test_normalize_leads_adds_ist_date_and_counselor_name():
    settings = make_settings()
    roster = pd.DataFrame([{"owner_id": "o1", "counselor_name": "Anuj Thakur",
                             "is_active": True, "is_excluded_owner": False}])
    df = pd.DataFrame([{"ProspectID": "1", "OwnerId": "o1", "OwnerIdName": "raw name",
                         "CreatedOn": "2026-09-01 05:00:00", "ModifiedOn": "2026-09-01 06:00:00",
                         "Source": "web ", "mx_Enquired_Course": "ACCA"}])

    out = normalize_leads(df, settings, "created_on", roster)

    assert out.loc[0, "counselor_name"] == "Anuj Thakur"
    assert out.loc[0, "is_excluded_owner"] == False
    assert out.loc[0, "ist_date"] is not None
    assert out.loc[0, "source"] == "web"


def test_normalize_leads_empty_input_returns_empty_frame_with_expected_columns():
    out = normalize_leads(pd.DataFrame(), make_settings(), "created_on", pd.DataFrame())
    assert out.empty
    assert "ist_date" in out.columns


def test_normalize_opportunities_renames_and_canonicalizes_stage():
    df = pd.DataFrame([{"lead_id": "1", "mx_Custom_2": "hot ", "Status": "Open", "mx_Custom_45": None}])
    out = normalize_opportunities(df, make_settings())
    assert out.loc[0, "opportunity_stage"] == "hot"
    assert out.loc[0, "opportunity_status"] == "Open"
