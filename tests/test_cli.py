import pytest

import cli
from funnellens.filters import Preset, Rule
from funnellens.pipeline import PipelineError


def test_list_reports_prints_every_registry_key(capsys):
    assert cli.main(["list-reports"]) == 0
    out = capsys.readouterr().out
    assert "lead_funnel" in out
    assert "raw" in out


def test_list_presets_with_none_defined(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_presets", lambda: [])
    assert cli.main(["list-presets"]) == 0
    assert "No presets" in capsys.readouterr().out


def test_list_presets_prints_names_and_rule_counts(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_presets", lambda: [Preset(name="Hot ACCA", rules=[Rule("source", "equals", "Web")])])
    assert cli.main(["list-presets"]) == 0
    assert "Hot ACCA (1 rule(s))" in capsys.readouterr().out


def test_verify_and_snapshot_are_stubs(capsys):
    assert cli.main(["verify", "--sheet", "x.xlsx", "--from", "2026-09-01", "--to", "2026-09-02"]) == 0
    assert "Phase 8" in capsys.readouterr().out
    assert cli.main(["snapshot"]) == 0
    assert "Phase 9" in capsys.readouterr().out


def test_generate_prints_friendly_error_without_traceback(monkeypatch, capsys):
    def boom(options, progress_callback=None):
        raise PipelineError("bad report key: nope")

    monkeypatch.setattr(cli, "run_pipeline", boom)
    exit_code = cli.main(["generate", "--reports", "nope", "--from", "2026-09-01", "--to", "2026-09-01"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "bad report key" in captured.err


def test_generate_with_debug_reraises(monkeypatch):
    def boom(options, progress_callback=None):
        raise PipelineError("bad report key: nope")

    monkeypatch.setattr(cli, "run_pipeline", boom)
    with pytest.raises(PipelineError):
        cli.main(["--debug", "generate", "--reports", "nope", "--from", "2026-09-01", "--to", "2026-09-01"])


def test_generate_reports_all_expands_to_every_registry_key(monkeypatch):
    captured_options = {}

    def fake_run_pipeline(options, progress_callback=None):
        captured_options["report_keys"] = options.report_keys
        return b"", {"output_path": "out.xlsx", "issues": []}

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)
    cli.main(["generate", "--reports", "all", "--from", "2026-09-01", "--to", "2026-09-01"])
    from funnellens.reports import REGISTRY
    assert captured_options["report_keys"] == list(REGISTRY)


def test_generate_parses_filter_strings_into_rules(monkeypatch):
    captured_options = {}

    def fake_run_pipeline(options, progress_callback=None):
        captured_options["filters"] = options.filters
        return b"", {"output_path": "out.xlsx", "issues": []}

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)
    cli.main(["generate", "--reports", "stage", "--from", "2026-09-01", "--to", "2026-09-01",
              "--filter", "course in ACCA,CMA"])
    rule = captured_options["filters"][0]
    assert rule.field == "course" and rule.op == "in" and rule.value == ["ACCA", "CMA"]


def test_generate_prints_output_path_and_issues(monkeypatch, capsys):
    def fake_run_pipeline(options, progress_callback=None):
        return b"", {"output_path": "output/FunnelLens_x.xlsx", "issues": ["Something looks off"]}

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)
    cli.main(["generate", "--reports", "stage", "--from", "2026-09-01", "--to", "2026-09-01"])
    out = capsys.readouterr().out
    assert "output/FunnelLens_x.xlsx" in out
    assert "Something looks off" in out


def test_invalid_date_format_is_a_friendly_error(capsys):
    exit_code = cli.main(["pull", "--from", "not-a-date", "--to", "2026-09-01"])
    assert exit_code == 1
    assert "Traceback" not in capsys.readouterr().err
