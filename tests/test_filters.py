import pandas as pd
import pytest

from funnellens.extract import Dataset
from funnellens.filters import (
    FilterError,
    Rule,
    apply_filters,
    apply_to_dataset,
    available_values,
    get_preset,
    load_presets,
    parse_filter_string,
)


def empty_dataset() -> Dataset:
    return Dataset(*(pd.DataFrame() for _ in range(6)))


# ---- Rule validation -------------------------------------------------------

def test_unknown_field_raises_clear_error():
    with pytest.raises(FilterError, match="Unknown filter field"):
        Rule(field="not_a_real_field", op="equals", value="x")


def test_unknown_operator_raises_clear_error():
    with pytest.raises(FilterError, match="Unknown filter operator"):
        Rule(field="source", op="fuzzy_match", value="x")


def test_in_requires_list_value():
    with pytest.raises(FilterError, match="requires a list"):
        Rule(field="source", op="in", value="Web")


def test_between_requires_two_item_value():
    with pytest.raises(FilterError, match="two-item"):
        Rule(field="created_on", op="between", value=[1])


# ---- Operators --------------------------------------------------------------

def test_equals_and_not_equals_are_case_insensitive_and_trimmed():
    df = pd.DataFrame({"source": ["Web", " web ", "Referral"]})
    matched = apply_filters(df, [Rule("source", "equals", "web")])
    assert len(matched) == 2
    not_matched = apply_filters(df, [Rule("source", "not_equals", "web")])
    assert not_matched["source"].tolist() == ["Referral"]


def test_in_gives_or_within_one_field():
    df = pd.DataFrame({"course": ["ACCA", "CMA", "CFA"]})
    result = apply_filters(df, [Rule("course", "in", ["acca", " cfa "])])
    assert sorted(result["course"]) == ["ACCA", "CFA"]


def test_not_in_excludes_listed_values():
    df = pd.DataFrame({"course": ["ACCA", "CMA", "CFA"]})
    result = apply_filters(df, [Rule("course", "not_in", ["ACCA"])])
    assert sorted(result["course"]) == ["CFA", "CMA"]


def test_contains_and_not_contains_are_substring_matches():
    df = pd.DataFrame({"course": ["ACCA Level 1", "CMA", "ACCA Level 2"]})
    result = apply_filters(df, [Rule("course", "contains", "acca")])
    assert len(result) == 2
    result = apply_filters(df, [Rule("course", "not_contains", "acca")])
    assert result["course"].tolist() == ["CMA"]


def test_is_empty_and_not_empty_treat_all_blank_variants_as_empty():
    df = pd.DataFrame({"source": ["", "  ", None, "nan", "none", "(Blank)", "Web"]})
    empty = apply_filters(df, [Rule("source", "is_empty", None)])
    assert len(empty) == 6
    not_empty = apply_filters(df, [Rule("source", "not_empty", None)])
    assert not_empty["source"].tolist() == ["Web"]


def test_numeric_comparisons():
    df = pd.DataFrame({"enrolled_date": [10, 20, 30]})
    result = apply_filters(df, [Rule("enrolled_date", "gte", 20)])
    assert result["enrolled_date"].tolist() == [20, 30]


def test_between_is_inclusive():
    df = pd.DataFrame({"enrolled_date": [5, 10, 15, 20]})
    result = apply_filters(df, [Rule("enrolled_date", "between", [10, 15])])
    assert result["enrolled_date"].tolist() == [10, 15]


def test_comparison_operators_never_crash_on_bad_data():
    df = pd.DataFrame({"enrolled_date": ["not-a-number", "20", None]})
    result = apply_filters(df, [Rule("enrolled_date", "gt", 5)])
    assert result["enrolled_date"].tolist() == ["20"]


def test_between_on_dates():
    df = pd.DataFrame({"created_on": pd.to_datetime(["2026-09-01", "2026-09-10", "2026-09-20"])})
    result = apply_filters(df, [Rule("created_on", "between", ["2026-09-05", "2026-09-15"])])
    assert len(result) == 1


# ---- AND / OR combination ----------------------------------------------------

def test_different_fields_combine_with_and():
    df = pd.DataFrame({"source": ["Web", "Web", "Referral"], "course": ["ACCA", "CMA", "ACCA"]})
    result = apply_filters(df, [Rule("source", "equals", "Web"), Rule("course", "equals", "ACCA")])
    assert len(result) == 1
    assert result.iloc[0]["course"] == "ACCA"


# ---- apply_to_dataset / excluded owners -------------------------------------

def make_dataset_with_owners() -> Dataset:
    leads_created = pd.DataFrame({
        "lead_id": ["1", "2"], "counselor_name": ["Anuj", "Bad Actor"], "is_excluded_owner": [False, True],
    })
    users = pd.DataFrame({
        "owner_id": ["o1", "o2"], "counselor_name": ["Anuj", "Bad Actor"], "is_excluded_owner": [False, True],
    })
    opportunities = pd.DataFrame({"lead_id": ["1", "2"], "opportunity_stage": ["Hot", "Cold"]})
    return Dataset(leads_created=leads_created, leads_modified=leads_created.copy(),
                    opportunities=opportunities, enrolments=pd.DataFrame(), tasks=pd.DataFrame(), users=users)


def test_excluded_owners_removed_by_default():
    dataset = make_dataset_with_owners()
    filtered = apply_to_dataset(dataset, [])
    assert filtered.leads_created["counselor_name"].tolist() == ["Anuj"]
    assert filtered.users["counselor_name"].tolist() == ["Anuj"]
    # unaffected -- opportunities has no is_excluded_owner column
    assert len(filtered.opportunities) == 2


def test_excluded_owners_kept_when_toggled_on():
    dataset = make_dataset_with_owners()
    filtered = apply_to_dataset(dataset, [], include_excluded_owners=True)
    assert sorted(filtered.leads_created["counselor_name"]) == ["Anuj", "Bad Actor"]


def test_apply_to_dataset_rule_only_applies_where_field_exists():
    dataset = make_dataset_with_owners()
    filtered = apply_to_dataset(dataset, [Rule("opportunity_stage", "equals", "Hot")], include_excluded_owners=True)
    assert filtered.opportunities["opportunity_stage"].tolist() == ["Hot"]
    # leads_created has no opportunity_stage column, so it is untouched by that rule
    assert len(filtered.leads_created) == 2


# ---- parse_filter_string ------------------------------------------------------

def test_parse_filter_string_in_operator():
    rule = parse_filter_string("course in ACCA,CMA")
    assert rule.field == "course"
    assert rule.op == "in"
    assert rule.value == ["ACCA", "CMA"]


def test_parse_filter_string_equals():
    rule = parse_filter_string("source equals Web")
    assert rule.value == "Web"


def test_parse_filter_string_is_empty_needs_no_value():
    rule = parse_filter_string("source is_empty")
    assert rule.value is None


def test_parse_filter_string_between():
    rule = parse_filter_string("enrolled_date between 2026-09-01,2026-09-30")
    assert rule.value == ["2026-09-01", "2026-09-30"]


def test_parse_filter_string_rejects_missing_value():
    with pytest.raises(FilterError):
        parse_filter_string("source equals")


def test_parse_filter_string_rejects_malformed_string():
    with pytest.raises(FilterError):
        parse_filter_string("source")


# ---- presets ------------------------------------------------------------------

def test_load_presets_parses_rules(tmp_path):
    path = tmp_path / "presets.yaml"
    path.write_text(
        "presets:\n"
        "  - name: Hot ACCA\n"
        "    rules:\n"
        "      - {field: course, op: equals, value: ACCA}\n"
        "      - {field: opportunity_stage, op: equals, value: Hot}\n",
        encoding="utf-8",
    )
    presets = load_presets(path)
    assert len(presets) == 1
    assert presets[0].name == "Hot ACCA"
    assert len(presets[0].rules) == 2


def test_load_presets_empty_file_returns_no_presets(tmp_path):
    path = tmp_path / "presets.yaml"
    path.write_text("presets: []\n", encoding="utf-8")
    assert load_presets(path) == []


def test_load_presets_rejects_bad_shape(tmp_path):
    path = tmp_path / "presets.yaml"
    path.write_text("presets:\n  - name: Missing Rules\n", encoding="utf-8")
    with pytest.raises(FilterError):
        load_presets(path)


def test_load_presets_rejects_unknown_field_in_a_rule(tmp_path):
    path = tmp_path / "presets.yaml"
    path.write_text(
        "presets:\n  - name: Bad\n    rules:\n      - {field: not_a_field, op: equals, value: x}\n",
        encoding="utf-8",
    )
    with pytest.raises(FilterError):
        load_presets(path)


def test_get_preset_returns_matching_preset(tmp_path):
    path = tmp_path / "presets.yaml"
    path.write_text(
        "presets:\n  - name: Hot ACCA\n    rules:\n      - {field: course, op: equals, value: ACCA}\n",
        encoding="utf-8",
    )
    preset = get_preset("Hot ACCA", path)
    assert preset.rules[0].field == "course"


def test_get_preset_raises_for_missing_name(tmp_path):
    path = tmp_path / "presets.yaml"
    path.write_text("presets: []\n", encoding="utf-8")
    with pytest.raises(FilterError):
        get_preset("Does Not Exist", path)


# ---- available_values ----------------------------------------------------------

def test_available_values_collects_across_frames_and_dedupes():
    dataset = make_dataset_with_owners()
    assert available_values(dataset, "counselor_name") == ["Anuj", "Bad Actor"]


def test_available_values_returns_empty_list_for_unused_field():
    dataset = empty_dataset()
    assert available_values(dataset, "source") == []
