"""Cleans raw pulls into consistent DataFrames: trimmed text, case-normalized values, standard columns.

Case-normalization (README Critical Rule 7): "ACCA", "acca " and "Acca" collapse
to one value, displayed as the most common original spelling. Missing values
become the literal string "(Blank)" -- never an empty name (Critical Rule 11).
"""

from __future__ import annotations

import re
from collections import Counter

import pandas as pd

from funnellens.extract import Dataset
from funnellens.settings import Settings
from funnellens.timeutil import from_lsq_utc_string

_WHITESPACE_RE = re.compile(r"\s+")
_BLANK = "(Blank)"


def _canonical_key(value: object) -> str:
    text = "" if value is None else str(value).strip()
    if not text or text.lower() in ("nan", "none"):
        return ""
    return _WHITESPACE_RE.sub(" ", text).lower()


def canonicalize_column(series: pd.Series) -> pd.Series:
    """Groups values by trimmed/lowercased key, replacing each with that group's most common
    original spelling. Blank, missing or whitespace-only values become "(Blank)"."""
    keys = [_canonical_key(v) for v in series]
    counts: dict[str, Counter] = {}
    for raw, key in zip(series, keys):
        if key:
            counts.setdefault(key, Counter())[_WHITESPACE_RE.sub(" ", str(raw).strip())] += 1
    winners = {key: counter.most_common(1)[0][0] for key, counter in counts.items()}
    return pd.Series([winners.get(k, _BLANK) for k in keys], index=series.index)


def _parse_datetime(value: object) -> object:
    if not isinstance(value, str) or not value.strip():
        return pd.NaT
    return from_lsq_utc_string(value)


def _renamed_or_empty(df: pd.DataFrame, field_to_internal: dict[str, str], columns: list[str]) -> pd.DataFrame:
    """Renames schema field names to internal names, or returns an empty frame with `columns` if df is empty."""
    if df.empty:
        return pd.DataFrame(columns=columns)
    return df.rename(columns=field_to_internal).copy()


def build_counselor_roster(users_df: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """One row per user: owner_id, counselor_name (FirstName + LastName, matching OwnerIdName's
    format), is_active and is_excluded_owner (role or name on the config.yaml exclusion lists)."""
    columns = ["owner_id", "counselor_name", "is_active", "is_excluded_owner"]
    if users_df.empty:
        return pd.DataFrame(columns=columns)
    roles_excluded = set(settings.excluded_owner_roles)
    names_excluded = set(settings.excluded_owner_names)
    rows = []
    for _, user in users_df.iterrows():
        first = str(user.get("FirstName") or "").strip()
        last = str(user.get("LastName") or "").strip()
        name = f"{first} {last}".strip() if last else first
        rows.append({
            "owner_id": user.get("ID"),
            "counselor_name": name,
            "is_active": user.get("StatusCode") == 0,
            "is_excluded_owner": user.get("Role") in roles_excluded or name in names_excluded,
        })
    return pd.DataFrame(rows, columns=columns)


def normalize_leads(df: pd.DataFrame, settings: Settings, date_field: str, roster: pd.DataFrame) -> pd.DataFrame:
    """Renames columns to internal names, adds ist_date + counselor_name/is_excluded_owner,
    and case-normalizes source/course. `date_field` ("created_on"/"modified_on") drives ist_date."""
    columns = ["lead_id", "owner_id", "owner_name", "created_on", "modified_on", "source", "course",
               "ist_date", "counselor_name", "is_excluded_owner"]
    field_to_internal = {settings.fields[key]: key
                          for key in ("lead_id", "owner_id", "owner_name", "created_on", "modified_on",
                                      "source", "course")}
    out = _renamed_or_empty(df, field_to_internal, columns)
    if out.empty:
        return out
    for col in ("created_on", "modified_on"):
        if col in out.columns:
            out[col] = out[col].map(_parse_datetime)
    out["ist_date"] = out[date_field].map(lambda dt: dt.date() if pd.notna(dt) else None)
    for col in ("source", "course"):
        if col in out.columns:
            out[col] = canonicalize_column(out[col])

    roster_name = roster.set_index("owner_id")["counselor_name"] if not roster.empty else pd.Series(dtype=str)
    roster_excluded = roster.set_index("owner_id")["is_excluded_owner"] if not roster.empty else pd.Series(dtype=bool)
    mapped_name = out["owner_id"].map(roster_name) if "owner_id" in out.columns else pd.Series(dtype=str)
    out["counselor_name"] = mapped_name.fillna(out.get("owner_name"))
    out["is_excluded_owner"] = (out["owner_id"].map(roster_excluded).fillna(False)
                                 if "owner_id" in out.columns else False)
    return out


def normalize_opportunities(df: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """Renames the Opportunity's stage/status/enrolled-date fields and case-normalizes stage.

    extract.py fetches opportunities per created-day window, so a lead created on one day and
    modified on another is fetched twice; every caller expects exactly one row per lead_id
    (e.g. stage_wise.py's `.set_index("lead_id")[...].get(lead_id)`), so duplicates are
    collapsed here once, keeping the last (most recently fetched, so closest to current)."""
    columns = ["lead_id", "opportunity_stage", "opportunity_status", "enrolled_date"]
    field_to_internal = {settings.fields["opportunity_stage"]: "opportunity_stage",
                          settings.fields["opportunity_status"]: "opportunity_status",
                          settings.fields["enrolled_date"]: "enrolled_date"}
    out = _renamed_or_empty(df, field_to_internal, columns)
    if out.empty:
        return out
    if "lead_id" in out.columns:
        out = out.drop_duplicates(subset="lead_id", keep="last")
    if "opportunity_stage" in out.columns:
        out["opportunity_stage"] = canonicalize_column(out["opportunity_stage"])
    if "enrolled_date" in out.columns:
        out["enrolled_date"] = out["enrolled_date"].map(_parse_datetime)
    return out


def normalize_enrolments(df: pd.DataFrame, settings: Settings, roster: pd.DataFrame) -> pd.DataFrame:
    """Renames the Opportunity Advanced Search result and maps Owner GUID to counselor name
    (P_Source is unreliable -- see LOGIC_SPEC.md section 2 -- so Source is not resolved here)."""
    columns = ["owner_id", "counselor_name", "lead_id", "opportunity_status", "opportunity_stage", "ist_date"]
    field_to_internal = {"Owner": "owner_id", "Status": "opportunity_status",
                          settings.fields["opportunity_stage"]: "opportunity_stage",
                          "RelatedProspectId": "lead_id"}
    out = _renamed_or_empty(df, field_to_internal, columns)
    if out.empty:
        return out
    if "opportunity_stage" in out.columns:
        out["opportunity_stage"] = canonicalize_column(out["opportunity_stage"])
    roster_name = roster.set_index("owner_id")["counselor_name"] if not roster.empty else pd.Series(dtype=str)
    out["counselor_name"] = out["owner_id"].map(roster_name) if "owner_id" in out.columns else None
    return out


def normalize_tasks(df: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    columns = ["lead_id", "task_due_date", "task_status"]
    field_to_internal = {settings.fields["task_due_date"]: "task_due_date",
                          settings.fields["task_status"]: "task_status"}
    out = _renamed_or_empty(df, field_to_internal, columns)
    if out.empty:
        return out
    if "task_due_date" in out.columns:
        out["task_due_date"] = out["task_due_date"].map(_parse_datetime)
    return out


def normalize_dataset(dataset: Dataset, settings: Settings) -> Dataset:
    """Applies every normalize_* step, returning a new Dataset with users replaced by the roster."""
    roster = build_counselor_roster(dataset.users, settings)
    return Dataset(
        leads_created=normalize_leads(dataset.leads_created, settings, "created_on", roster),
        leads_modified=normalize_leads(dataset.leads_modified, settings, "modified_on", roster),
        opportunities=normalize_opportunities(dataset.opportunities, settings),
        enrolments=normalize_enrolments(dataset.enrolments, settings, roster),
        tasks=normalize_tasks(dataset.tasks, settings),
        users=roster,
    )
