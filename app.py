"""Streamlit web page: date range, report picker, filters, Generate, Download Excel.

Two-step flow (README section 8): "Load data" fetches once and keeps the normalized
Dataset in st.session_state; everything after that (filters, report choice, Generate) is
local-only and calls funnellens/pipeline.py's build_workbook() directly, making no new API
calls except final_count.py's live Overdues snapshot. All business logic lives in
funnellens/pipeline.py, filters.py and reports/ -- this file is UI only.
"""

from __future__ import annotations

import os
import traceback
from datetime import date, datetime, timedelta, timezone

import streamlit as st

from funnellens.export import OUTPUT_DIR, write_workbook
from funnellens.filters import (
    KNOWN_FIELDS, OPERATORS, FilterError, Rule, available_values, load_presets, save_preset,
)
from funnellens.lsq_client import LSQClient, LSQError
from funnellens.pipeline import PipelineError, PipelineOptions, build_report_results, fetch_and_normalize
from funnellens.reports import REGISTRY
from funnellens.settings import SettingsError, load_settings
from funnellens.timeutil import IST

st.set_page_config(page_title="FunnelLens", layout="wide")

MULTISELECT_FIELDS = {"Counselor": "counselor_name", "Source": "source", "Course": "course", "Stage": "opportunity_stage"}


def _friendly_error(exc: Exception) -> None:
    st.error(str(exc))
    with st.expander("Technical details"):
        st.code("".join(traceback.format_exception(exc)))


def _check_password() -> bool:
    """A shared app password from secrets/env, for when the app is hosted (README section 12).
    No password configured -> no gate, for local/dev use."""
    expected = None
    try:
        expected = st.secrets.get("APP_PASSWORD")
    except Exception:
        pass
    expected = expected or os.environ.get("FUNNELLENS_APP_PASSWORD")
    if not expected:
        return True
    if st.session_state.get("authenticated"):
        return True
    password = st.text_input("App password", type="password")
    if password == expected:
        st.session_state["authenticated"] = True
        st.rerun()
    elif password:
        st.error("Incorrect password.")
    return False


def _load_data(from_date: date, to_date: date, force_refresh: bool) -> None:
    progress = st.progress(0.0, text="Starting...")

    def report(stage: str, done: int, total: int) -> None:
        progress.progress(done / total if total else 1.0, text=f"{stage}: {done}/{total}")

    settings = load_settings()
    client = LSQClient(settings)
    dataset = fetch_and_normalize(from_date, to_date, settings, client, progress_callback=report,
                                   force_refresh=force_refresh)
    progress.empty()
    st.session_state["dataset"] = dataset
    st.session_state["settings"] = settings
    st.session_state["client"] = client
    st.session_state["loaded_range"] = (from_date, to_date)
    st.session_state.pop("generated", None)


def _advanced_rules_editor() -> list[Rule]:
    st.session_state.setdefault("advanced_rules", [])
    with st.expander("Advanced rules"):
        cols = st.columns([3, 2, 3, 1])
        field = cols[0].selectbox("Field", sorted(KNOWN_FIELDS), key="adv_field")
        op = cols[1].selectbox("Operator", OPERATORS, key="adv_op")
        value = cols[2].text_input("Value (comma-separated for in/not_in/between)", key="adv_value")
        if cols[3].button("Add"):
            try:
                raw_value: object = value
                if op in ("in", "not_in"):
                    raw_value = [v.strip() for v in value.split(",")]
                elif op == "between":
                    raw_value = [v.strip() for v in value.split(",")]
                elif op in ("is_empty", "not_empty"):
                    raw_value = None
                st.session_state["advanced_rules"].append(Rule(field, op, raw_value))
            except FilterError as exc:
                st.error(str(exc))

        for i, rule in enumerate(st.session_state["advanced_rules"]):
            row = st.columns([8, 1])
            row[0].write(f"{rule.field} {rule.op} {rule.value}")
            if row[1].button("Remove", key=f"remove_rule_{i}"):
                st.session_state["advanced_rules"].pop(i)
                st.rerun()
    return list(st.session_state["advanced_rules"])


def _save_preset_form(rules: list[Rule]) -> None:
    with st.expander("Save current filters as a preset"):
        name = st.text_input("Preset name", key="new_preset_name")
        if st.button("Save preset"):
            try:
                save_preset(name, rules)
                st.success(f"Saved preset {name!r}.")
            except FilterError as exc:
                st.error(str(exc))


def main() -> None:
    st.title("FunnelLens: LeadSquared reports in one click")

    if not _check_password():
        return

    yesterday = datetime.now(timezone.utc).astimezone(IST).date() - timedelta(days=1)

    with st.sidebar:
        st.header("Date range")
        from_date = st.date_input("From", value=yesterday)
        to_date = st.date_input("To", value=yesterday)
        force_refresh = st.toggle("Force refresh", value=False)
        load_clicked = st.button("Load data", type="primary", key="load_data_btn")

    if load_clicked:
        try:
            _load_data(from_date, to_date, force_refresh)
        except (SettingsError, LSQError, PipelineError, ValueError) as exc:
            _friendly_error(exc)
            return

    dataset = st.session_state.get("dataset")
    if dataset is None:
        st.info("Pick a date range and click **Load data** to get started.")
        return

    loaded_from, loaded_to = st.session_state["loaded_range"]
    if (from_date, to_date) != (loaded_from, loaded_to):
        st.warning(f"Loaded data is for {loaded_from} to {loaded_to}. Click **Load data** to reload for the new range.")

    with st.sidebar:
        st.header("Reports")
        select_all = st.checkbox("Select all", value=True)
        report_keys = [key for key, (_, title) in REGISTRY.items() if key != "raw"
                       and st.checkbox(title, value=select_all, key=f"report_{key}")]

        st.header("Filters")
        presets = load_presets()
        preset_name = st.selectbox("Preset", ["(none)"] + [p.name for p in presets])

        multiselect_rules = []
        for label, field in MULTISELECT_FIELDS.items():
            options = available_values(dataset, field)
            selected = st.multiselect(label, options)
            if selected:
                multiselect_rules.append(Rule(field, "in", selected))

        advanced_rules = _advanced_rules_editor()
        include_excluded_owners = st.toggle("Include excluded owners", value=False)
        mask_pii = st.toggle("Mask phone/email", value=True)

        _save_preset_form(multiselect_rules + advanced_rules)

    st.subheader("Generate")
    if st.button("Generate", type="primary", key="generate_btn"):
        if not report_keys:
            st.error("Select at least one report.")
        else:
            options = PipelineOptions(
                from_date=loaded_from, to_date=loaded_to, report_keys=report_keys,
                filters=multiselect_rules + advanced_rules,
                preset=None if preset_name == "(none)" else preset_name,
                include_excluded_owners=include_excluded_owners, mask_pii=mask_pii,
            )
            try:
                results, run_info = build_report_results(dataset, options, st.session_state["settings"],
                                                           st.session_state["client"])
                out_path = OUTPUT_DIR / f"FunnelLens_{loaded_from}_to_{loaded_to}.xlsx"
                data = write_workbook(results, run_info, path=out_path)
                run_info["output_path"] = str(out_path)
                st.session_state["generated"] = {"data": data, "run_info": run_info, "results": results}
            except (PipelineError, FilterError, LSQError) as exc:
                _friendly_error(exc)

    generated = st.session_state.get("generated")
    if generated:
        run_info = generated["run_info"]
        if run_info["issues"]:
            with st.expander(f"{len(run_info['issues'])} issue(s) found", expanded=True):
                for issue in run_info["issues"]:
                    st.write(f"- {issue}")

        results_by_key = {r.key: r for r in generated["results"]}
        tabs = st.tabs([REGISTRY[key][1] for key in report_keys])
        for tab, key in zip(tabs, report_keys):
            with tab:
                # Total rows blank non-summed cells with "" (LOGIC_SPEC.md), which mixed into an
                # otherwise numeric/date column makes Arrow (Streamlit's table serializer) guess
                # wrong and log a conversion warning; None lets it infer a clean nullable column.
                preview = results_by_key[key].dataframe.drop(columns=["is_total"], errors="ignore").replace("", None)
                st.dataframe(preview)

        st.download_button("Download Excel", data=generated["data"],
                            file_name=os.path.basename(run_info["output_path"]),
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


if __name__ == "__main__":
    main()
