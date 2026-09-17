"""Small hand-made Dataset fixture for Phase 4 report tests, with known correct answers
worked out by hand in tests/test_reports.py's module docstring-adjacent comments.

Two counselors (Alice, Bob), two days (2026-09-01, 2026-09-02), both inside one month so
Monthly rollups need no data outside the fixture's own two days.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd

from funnellens.extract import Dataset

DAY1 = date(2026, 9, 1)
DAY2 = date(2026, 9, 2)
RUN_AT = datetime(2026, 9, 3, 4, 30, 0, tzinfo=timezone.utc)  # after both days -- everything due before this is overdue


def build_fixture_dataset() -> Dataset:
    leads_created = pd.DataFrame([
        {"lead_id": "L1", "owner_id": "a1", "owner_name": "Alice", "counselor_name": "Alice",
         "is_excluded_owner": False, "ist_date": DAY1, "source": "Web", "course": "ACCA"},
        {"lead_id": "L2", "owner_id": "a1", "owner_name": "Alice", "counselor_name": "Alice",
         "is_excluded_owner": False, "ist_date": DAY1, "source": "Web", "course": "ACCA"},
        {"lead_id": "L3", "owner_id": "b1", "owner_name": "Bob", "counselor_name": "Bob",
         "is_excluded_owner": False, "ist_date": DAY1, "source": "Referrals", "course": "CMA"},
        {"lead_id": "L4", "owner_id": "a1", "owner_name": "Alice", "counselor_name": "Alice",
         "is_excluded_owner": False, "ist_date": DAY2, "source": "Web", "course": "ACCA"},
        {"lead_id": "L5", "owner_id": "b1", "owner_name": "Bob", "counselor_name": "Bob",
         "is_excluded_owner": False, "ist_date": DAY2, "source": "Referrals", "course": "CMA"},
    ])

    leads_modified = pd.DataFrame([
        {"lead_id": "L1", "owner_id": "a1", "owner_name": "Alice", "counselor_name": "Alice",
         "is_excluded_owner": False, "ist_date": DAY1, "source": "Web", "course": "ACCA"},
        {"lead_id": "L2", "owner_id": "a1", "owner_name": "Alice", "counselor_name": "Alice",
         "is_excluded_owner": False, "ist_date": DAY2, "source": "Web", "course": "ACCA"},
        {"lead_id": "L3", "owner_id": "b1", "owner_name": "Bob", "counselor_name": "Bob",
         "is_excluded_owner": False, "ist_date": DAY2, "source": "Referrals", "course": "CMA"},
    ])

    opportunities = pd.DataFrame([
        {"lead_id": "L1", "opportunity_stage": "Hot", "opportunity_status": "Open"},
        {"lead_id": "L2", "opportunity_stage": "Not Reachable", "opportunity_status": "Open"},
        {"lead_id": "L3", "opportunity_stage": "Cold", "opportunity_status": "Lost"},
        {"lead_id": "L5", "opportunity_stage": "Enrolled", "opportunity_status": "Open"},
        # L4 has no opportunity row at all -> Stage Wise "Not Modified"
    ])

    before_run = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    after_run = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
    tasks = pd.DataFrame([
        {"lead_id": "L1", "task_due_date": before_run, "task_status": "Pending"},
        {"lead_id": "L1", "task_due_date": before_run, "task_status": "Completed"},
        {"lead_id": "L2", "task_due_date": before_run, "task_status": "Pending"},
        {"lead_id": "L4", "task_due_date": after_run, "task_status": "Pending"},
        # L3 and L5 have zero tasks -> "No Task"
    ])

    enrolments = pd.DataFrame([
        {"owner_id": "b1", "counselor_name": "Bob", "lead_id": "L5", "opportunity_status": "Open",
         "opportunity_stage": "Enrolled", "ist_date": DAY2},
    ])

    users = pd.DataFrame([
        {"owner_id": "a1", "counselor_name": "Alice", "is_active": True, "is_excluded_owner": False},
        {"owner_id": "b1", "counselor_name": "Bob", "is_active": True, "is_excluded_owner": False},
    ])

    return Dataset(leads_created=leads_created, leads_modified=leads_modified, opportunities=opportunities,
                    enrolments=enrolments, tasks=tasks, users=users)
