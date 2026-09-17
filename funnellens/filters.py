"""Local filter rules engine ({field, op, value}) and preset handling.

Stage 2 filtering only (README Section 8.2) -- everything here runs on
DataFrames already pulled and normalized (funnellens/normalize.py). No API
calls. Text comparisons are case-insensitive and trimmed; is_empty treats
"", NaN, None, "nan", "none" and "(Blank)" (normalize.py's blank marker) as
empty. Different rules combine with AND; `in`/`not_in` give OR within one field.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field, fields as dataclass_fields
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from funnellens.extract import Dataset

PRESETS_PATH = Path(__file__).resolve().parent.parent / "config" / "presets.yaml"

OPERATORS = (
    "equals", "not_equals", "in", "not_in", "contains", "not_contains",
    "is_empty", "not_empty", "gt", "gte", "lt", "lte", "between",
)

# Every column normalize.py can produce, across every Dataset frame.
KNOWN_FIELDS = frozenset({
    "lead_id", "owner_id", "owner_name", "counselor_name", "is_excluded_owner", "is_active",
    "created_on", "modified_on", "ist_date", "source", "course",
    "opportunity_stage", "opportunity_status", "enrolled_date",
    "task_due_date", "task_status",
})

_EMPTY_TOKENS = {"", "nan", "none", "(blank)"}
_LIST_OPERATORS = ("in", "not_in")
_COMPARISON_OPERATORS = ("gt", "gte", "lt", "lte", "between")


class FilterError(Exception):
    """Raised for an invalid Rule, filter string or presets.yaml entry."""


@dataclass
class Rule:
    field: str
    op: str
    value: Any = None

    def __post_init__(self) -> None:
        if self.field not in KNOWN_FIELDS:
            raise FilterError(f"Unknown filter field: {self.field!r}")
        if self.op not in OPERATORS:
            raise FilterError(f"Unknown filter operator: {self.op!r}")
        if self.op in _LIST_OPERATORS and not isinstance(self.value, (list, tuple, set)):
            raise FilterError(f"Operator {self.op!r} requires a list value, got {type(self.value).__name__}")
        if self.op == "between" and (not isinstance(self.value, (list, tuple)) or len(self.value) != 2):
            raise FilterError("Operator 'between' requires a two-item [low, high] value")


@dataclass
class Preset:
    name: str
    rules: list[Rule] = dc_field(default_factory=list)


def _norm_text(value: Any) -> str:
    return str(value).strip().lower()


def _text_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower()


def _is_empty_mask(series: pd.Series) -> pd.Series:
    return series.isna() | _text_series(series).isin(_EMPTY_TOKENS)


def _coerce_numeric_or_datetime(series: pd.Series) -> tuple[pd.Series, str]:
    """Picks numeric or datetime coercion for a column, so gt/gte/lt/lte/between never crash
    on bad data -- unparseable values just become NaN/NaT and never match."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce"), "datetime"
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().any() or series.dropna().empty:
        return numeric, "numeric"
    return pd.to_datetime(series, errors="coerce"), "datetime"


def _coerce_value(value: Any, kind: str) -> Any:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce") if kind == "datetime" else pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else parsed


def _apply_comparison(series: pd.Series, op: str, value: Any) -> pd.Series:
    coerced, kind = _coerce_numeric_or_datetime(series)
    if op == "between":
        low, high = (_coerce_value(v, kind) for v in value)
        if low is None or high is None:
            return pd.Series(False, index=series.index)
        return (coerced >= low) & (coerced <= high)
    target = _coerce_value(value, kind)
    if target is None:
        return pd.Series(False, index=series.index)
    return {"gt": coerced > target, "gte": coerced >= target,
            "lt": coerced < target, "lte": coerced <= target}[op]


def _apply_rule_to_series(series: pd.Series, rule: Rule) -> pd.Series:
    if rule.op == "is_empty":
        return _is_empty_mask(series)
    if rule.op == "not_empty":
        return ~_is_empty_mask(series)
    if rule.op in _COMPARISON_OPERATORS:
        return _apply_comparison(series, rule.op, rule.value)

    text = _text_series(series)
    if rule.op == "equals":
        return text == _norm_text(rule.value)
    if rule.op == "not_equals":
        return text != _norm_text(rule.value)
    if rule.op == "in":
        return text.isin({_norm_text(v) for v in rule.value})
    if rule.op == "not_in":
        return ~text.isin({_norm_text(v) for v in rule.value})
    if rule.op == "contains":
        return text.str.contains(_norm_text(rule.value), regex=False, na=False)
    if rule.op == "not_contains":
        return ~text.str.contains(_norm_text(rule.value), regex=False, na=False)
    raise FilterError(f"Unsupported operator: {rule.op!r}")  # unreachable -- Rule validates op


def apply_filters(df: pd.DataFrame, rules: list[Rule]) -> pd.DataFrame:
    """Applies every rule whose field is a column of df (AND between rules); rules for
    columns df doesn't have are skipped, so the same rule list can target several frames."""
    if df.empty:
        return df
    mask = pd.Series(True, index=df.index)
    for rule in rules:
        if rule.field in df.columns:
            mask &= _apply_rule_to_series(df[rule.field], rule)
    return df[mask].reset_index(drop=True)


EXCLUDED_OWNERS_RULE = Rule(field="is_excluded_owner", op="equals", value=False)


def apply_to_dataset(dataset: Dataset, rules: list[Rule], include_excluded_owners: bool = False) -> Dataset:
    """Applies `rules` to every DataFrame in dataset. Excluded owners (config.yaml's
    excluded_owner_roles/names, via normalize.py's is_excluded_owner column) are removed
    unless include_excluded_owners is True."""
    effective_rules = list(rules) if include_excluded_owners else [*rules, EXCLUDED_OWNERS_RULE]
    return Dataset(**{
        f.name: apply_filters(getattr(dataset, f.name), effective_rules)
        for f in dataclass_fields(Dataset)
    })


def parse_filter_string(text: str) -> Rule:
    """Parses "<field> <op> [value]", e.g. "course in ACCA,CMA" or "created_on is_empty"."""
    parts = text.strip().split(None, 2)
    if len(parts) < 2:
        raise FilterError(f"Invalid filter string: {text!r}. Expected '<field> <op> [value]'.")
    field, op = parts[0], parts[1]
    raw_value = parts[2].strip() if len(parts) > 2 else None

    if op in ("is_empty", "not_empty"):
        value: Any = None
    elif op in _LIST_OPERATORS:
        if not raw_value:
            raise FilterError(f"Operator {op!r} requires a comma-separated value list.")
        value = [v.strip() for v in raw_value.split(",")]
    elif op == "between":
        bounds = [v.strip() for v in raw_value.split(",")] if raw_value else []
        if len(bounds) != 2:
            raise FilterError("Operator 'between' requires exactly two comma-separated values: 'low,high'.")
        value = bounds
    else:
        if not raw_value:
            raise FilterError(f"Operator {op!r} requires a value.")
        value = raw_value

    return Rule(field=field, op=op, value=value)


def load_presets(path: Path | None = None) -> list[Preset]:
    path = path or PRESETS_PATH
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    raw_presets = raw.get("presets") or []
    if not isinstance(raw_presets, list):
        raise FilterError(f"{path}: 'presets' must be a list")

    presets = []
    for item in raw_presets:
        if not isinstance(item, dict) or "name" not in item or "rules" not in item:
            raise FilterError(f"{path}: each preset needs 'name' and 'rules': {item!r}")
        try:
            rules = [Rule(**rule) for rule in item["rules"]]
        except TypeError as exc:
            raise FilterError(f"{path}: preset {item.get('name')!r} has an invalid rule: {exc}") from exc
        presets.append(Preset(name=item["name"], rules=rules))
    return presets


def get_preset(name: str, path: Path | None = None) -> Preset:
    for preset in load_presets(path):
        if preset.name == name:
            return preset
    raise FilterError(f"No preset named {name!r} found in {path or PRESETS_PATH}")


def save_preset(name: str, rules: list[Rule], path: Path | None = None) -> None:
    """Appends a new preset to presets.yaml. Raises FilterError for a blank name or one that
    already exists (case-insensitive)."""
    path = path or PRESETS_PATH
    name = name.strip()
    if not name:
        raise FilterError("Preset name can't be blank.")
    existing = load_presets(path)
    if any(p.name.strip().lower() == name.lower() for p in existing):
        raise FilterError(f"A preset named {name!r} already exists.")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    raw.setdefault("presets", [])
    raw["presets"].append({"name": name, "rules": [{"field": r.field, "op": r.op, "value": r.value} for r in rules]})
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, sort_keys=False, allow_unicode=True)


def available_values(dataset: Dataset, field: str) -> list[str]:
    """Sorted, deduplicated display values for `field` across every Dataset frame that has it -- for UI dropdowns."""
    values: set[str] = set()
    for f in dataclass_fields(Dataset):
        df = getattr(dataset, f.name)
        if field in df.columns:
            values.update(str(v) for v in df[field].dropna().unique())
    return sorted(values)
