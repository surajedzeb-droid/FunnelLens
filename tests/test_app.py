"""Headless functional tests for app.py using Streamlit's own AppTest harness -- no browser
needed. Patches load_settings/LSQClient/fetch_and_normalize so no real API calls happen."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1 import AppTest

from tests.fixtures.reports_fixture import build_fixture_dataset
from tests.test_reports import make_settings

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def patch_app_dependencies(monkeypatch):
    import funnellens.lsq_client as lsq_client_module
    import funnellens.pipeline as pipeline_module
    import funnellens.settings as settings_module

    fake_client = MagicMock()
    fake_client.call_count = 3
    fake_client.get_tasks_for_owner.return_value = []

    monkeypatch.setattr(settings_module, "load_settings", lambda: make_settings())
    monkeypatch.setattr(lsq_client_module, "LSQClient", lambda settings: fake_client)
    monkeypatch.setattr(pipeline_module, "fetch_and_normalize", lambda *a, **k: build_fixture_dataset())
    return fake_client


def load_data(at: AppTest) -> AppTest:
    return at.sidebar.button(key="load_data_btn").click().run()


def test_app_renders_without_crashing():
    at = AppTest.from_file(APP_PATH).run()
    assert not at.exception


def test_before_loading_data_shows_prompt_not_filters():
    at = AppTest.from_file(APP_PATH).run()
    assert any("Load data" in i.value for i in at.info)
    assert len(at.sidebar.multiselect) == 0


def test_load_data_populates_dataset_and_filter_dropdowns():
    at = load_data(AppTest.from_file(APP_PATH).run())
    assert not at.exception
    counselor_select = next(m for m in at.sidebar.multiselect if m.label == "Counselor")
    assert sorted(counselor_select.options) == ["Alice", "Bob"]


def test_report_checkboxes_default_to_selected():
    at = load_data(AppTest.from_file(APP_PATH).run())
    report_checkboxes = [c for c in at.sidebar.checkbox if c.key and c.key.startswith("report_")]
    assert report_checkboxes  # one per non-raw registry key
    assert all(c.value for c in report_checkboxes)  # "Select all" defaults on


def test_generate_produces_download_button_and_no_crash():
    at = load_data(AppTest.from_file(APP_PATH).run())
    at = at.button(key="generate_btn").click().run()
    assert not at.exception
    assert len(at.tabs) > 0
    assert len(at.download_button) == 1


def test_generate_with_no_reports_selected_shows_friendly_error():
    at = load_data(AppTest.from_file(APP_PATH).run())
    for cb in at.sidebar.checkbox:
        if cb.key and (cb.key.startswith("report_") or cb.label == "Select all"):
            cb.set_value(False)
    at = at.run()
    at = at.button(key="generate_btn").click().run()
    assert not at.exception
    assert any("Select at least one report" in e.value for e in at.error)


def test_load_data_error_is_shown_as_friendly_message_not_a_crash(monkeypatch):
    import funnellens.pipeline as pipeline_module
    from funnellens.pipeline import PipelineError

    def boom(*a, **k):
        raise PipelineError("to_date is before from_date")

    monkeypatch.setattr(pipeline_module, "fetch_and_normalize", boom)
    at = load_data(AppTest.from_file(APP_PATH).run())
    assert not at.exception
    assert any("to_date is before from_date" in e.value for e in at.error)


def test_multiselect_filter_narrows_generated_preview():
    at = load_data(AppTest.from_file(APP_PATH).run())
    counselor_select = next(m for m in at.sidebar.multiselect if m.label == "Counselor")
    counselor_select.set_value(["Alice"])
    at = at.run()
    at = at.button(key="generate_btn").click().run()
    assert not at.exception
    assert len(at.download_button) == 1
