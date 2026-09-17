"""Internal consistency checks across built reports (Phase 4 acceptance criteria).
Returns plain issue strings -- callers decide what to do with them (log, fail a test, etc.)."""

from __future__ import annotations

import pandas as pd

from funnellens.reports import ReportResult

_SUSPICIOUS_VALUES = {500, 1000, 100000}


def _numeric_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns
            if c not in ("Date", "Counselor Name", "Till Date", "is_total", "") and pd.api.types.is_numeric_dtype(df[c])]


def _summable_columns(df: pd.DataFrame) -> list[str]:
    """Numeric columns that are actual counts/sums. Percentage columns are independently
    recomputed formulas on the Total row (e.g. Disqualified % of the grand total), never a
    sum of the block's own per-row percentages, so they're excluded here."""
    return [c for c in _numeric_columns(df) if not (isinstance(c, str) and c.strip().endswith("%"))]


def check_total_rows_match_their_block(result: ReportResult) -> list[str]:
    """Each Total row must equal the sum of the day-block rows directly above it."""
    df = result.dataframe
    if df.empty or "is_total" not in df.columns:
        return []
    numeric_cols = _summable_columns(df)
    issues, block = [], []
    for idx, row in df.iterrows():
        if row["is_total"]:
            block_df = df.loc[block]
            for col in numeric_cols:
                expected = block_df[col].sum() if not block_df.empty else 0
                actual = row[col]
                if actual != "" and pd.notna(actual) and abs(float(actual) - float(expected)) > 1e-9:
                    issues.append(f"{result.title}: Total row at index {idx}, column {col!r} is {actual}, "
                                  f"expected {expected} (sum of the block above it)")
            block = []
        else:
            block.append(idx)
    return issues


def check_no_duplicate_counselors(result: ReportResult) -> list[str]:
    """Final Count has exactly one row per counselor (per month)."""
    df = result.dataframe
    if df.empty or "Counselor Name" not in df.columns:
        return []
    names = df.loc[~df["is_total"], "Counselor Name"] if "is_total" in df.columns else df["Counselor Name"]
    duplicates = sorted(names[names.duplicated()].unique())
    return [f"{result.title}: duplicate counselor row(s): {duplicates}"] if duplicates else []


def check_no_blank_named_columns(result: ReportResult) -> list[str]:
    """No column header is blank/whitespace, except Stage Wise's one deliberate spacer column."""
    blanks = [c for c in result.dataframe.columns
              if isinstance(c, str) and c.strip() == "" and c != "" and c != "is_total"]
    return [f"{result.title}: blank-named column: {c!r}" for c in blanks]


def check_no_suspicious_round_numbers(result: ReportResult) -> list[str]:
    """No value sits exactly at 500, 1000 or 100000 -- the exact caps README Critical Rule 9 warns about."""
    issues = []
    for col in _numeric_columns(result.dataframe):
        for value in result.dataframe.loc[result.dataframe[col].isin(_SUSPICIOUS_VALUES), col].unique():
            issues.append(f"{result.title}: column {col!r} has a value of exactly {value} -- "
                           f"check it isn't a silent cap (README Critical Rule 9)")
    return issues


def check_created_totals_match_across_reports(results: dict[str, ReportResult]) -> list[str]:
    """Lead Funnel, Stage Wise, Source Wise and Course Wise all count the same created-leads-
    per-day; their Total rows should agree for each day (LOGIC_SPEC.md sections 3.1-3.4)."""
    column_by_key = {"lead_funnel": "Created On_Day wise", "stage": "Total", "source": "Total", "course": "Total"}
    totals: dict[str, dict] = {}
    for key, col in column_by_key.items():
        result = results.get(key)
        if result is None or result.dataframe.empty or "is_total" not in result.dataframe.columns:
            continue
        total_rows = result.dataframe[result.dataframe["is_total"]]
        totals[key] = dict(zip(total_rows["Date"].astype(str), total_rows[col]))

    issues = []
    keys = list(totals)
    if not keys:
        return issues
    reference = keys[0]
    for day, expected in totals[reference].items():
        for key in keys[1:]:
            actual = totals[key].get(day)
            if actual is not None and actual != expected:
                issues.append(f"Created total mismatch on {day}: {reference}={expected}, {key}={actual}")
    return issues


def check_monthly_rollup_matches_daily_sum(result: ReportResult, monthly_column: str, daily_column: str) -> list[str]:
    """A Monthly-ish column on a given row should equal that counselor's own daily-column sum
    from month-start through that row's date, using only the days visible in this report's own
    output -- accurate as long as the caller pulled the whole month (README "pull once")."""
    df = result.dataframe
    if df.empty or "is_total" not in df.columns:
        return []
    rows = df[~df["is_total"]].copy()
    rows["_date"] = pd.to_datetime(rows["Date"])
    issues = []
    for counselor, group in rows.groupby("Counselor Name"):
        group = group.sort_values("_date")
        for _, row in group.iterrows():
            month_start = row["_date"].replace(day=1)
            window = group[(group["_date"] >= month_start) & (group["_date"] <= row["_date"])]
            expected = window[daily_column].sum()
            if row[monthly_column] != expected:
                issues.append(f"{result.title}: {counselor} {row['Date']}: {monthly_column}={row[monthly_column]}, "
                              f"expected {expected} (sum of {daily_column} for the month so far)")
    return issues


def run_checks(results: dict[str, ReportResult]) -> list[str]:
    issues: list[str] = []
    for result in results.values():
        issues += check_total_rows_match_their_block(result)
        issues += check_no_blank_named_columns(result)
        issues += check_no_suspicious_round_numbers(result)
    if "final" in results:
        issues += check_no_duplicate_counselors(results["final"])
    issues += check_created_totals_match_across_reports(results)
    if "lead_funnel" in results:
        issues += check_monthly_rollup_matches_daily_sum(results["lead_funnel"], "Created On (Monthly)", "Created On_Day wise")
        issues += check_monthly_rollup_matches_daily_sum(results["lead_funnel"], "Modified On (Monthly)", "Modified On (Daily)")
    return issues
