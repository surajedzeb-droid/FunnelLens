"""The core pipeline: fetch_dataset -> normalize -> filter -> build reports -> run checks
-> write the workbook. cli.py's `generate` command and app.py's web UI both build on this
module so they can never disagree about what a "run" does (Phase 6 prompt rule: "The CLI
and the future web app must share the same pipeline code").

Split into two steps because the web app needs them separately (README Section 8.1/8.2:
fetch once, then filter/re-filter locally with no new API calls):
- fetch_and_normalize(): the only step that talks to LeadSquared.
- build_workbook(): filter -> reports -> checks -> export, a pure function of an
  already-fetched Dataset -- callable as many times as the user changes filters.
run_pipeline() is both steps back to back, for the CLI's one-shot `generate` command.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from funnellens.checks import run_checks
from funnellens.export import OUTPUT_DIR, write_workbook
from funnellens.extract import Dataset, fetch_dataset
from funnellens.filters import Rule, apply_to_dataset, get_preset
from funnellens.lsq_client import LSQClient
from funnellens.normalize import normalize_dataset
from funnellens.reports import REGISTRY, ReportContext, ReportResult
from funnellens.settings import Settings, load_settings

ProgressCallback = Callable[[str, int, int], None]


class PipelineError(Exception):
    """Raised for a bad option (unknown report key, invalid date range, unknown preset)."""


@dataclass
class PipelineOptions:
    from_date: date
    to_date: date
    report_keys: list[str]
    owners: list[str] | None = None
    filters: list[Rule] = field(default_factory=list)
    preset: str | None = None
    include_excluded_owners: bool = False
    mask_pii: bool = False
    force_refresh: bool = False
    out_path: str | Path | None = None


def fetch_and_normalize(from_date: date, to_date: date, settings: Settings, client: LSQClient,
                         owners: list[str] | None = None, progress_callback: ProgressCallback | None = None,
                         force_refresh: bool = False) -> Dataset:
    if to_date < from_date:
        raise PipelineError(f"to_date ({to_date}) is before from_date ({from_date})")
    dataset = fetch_dataset(from_date, to_date, settings, client=client, owners=owners,
                             progress_callback=progress_callback, force_refresh=force_refresh)
    return normalize_dataset(dataset, settings)


def build_report_results(dataset: Dataset, options: PipelineOptions, settings: Settings,
                          client: LSQClient) -> tuple[list[ReportResult], dict]:
    """Filter -> reports -> checks, without exporting. Shared by build_workbook() (which also
    writes the file, for the CLI) and app.py (which additionally needs the ReportResults
    themselves for its preview tabs, so it must not build them a second time to export)."""
    unknown = [k for k in options.report_keys if k not in REGISTRY]
    if unknown:
        raise PipelineError(f"Unknown report key(s): {', '.join(unknown)}. Valid keys: {', '.join(REGISTRY)}")

    rules = list(options.filters)
    if options.preset:
        try:
            rules += get_preset(options.preset).rules
        except FileNotFoundError as exc:
            raise PipelineError(f"Presets file not found: {exc}") from exc
    filtered = apply_to_dataset(dataset, rules, include_excluded_owners=options.include_excluded_owners)

    now = datetime.now(timezone.utc)
    context = ReportContext(settings=settings, run_at=now, client=client, mask_pii=options.mask_pii)
    report_keys = options.report_keys if "raw" in options.report_keys else [*options.report_keys, "raw"]
    results = [REGISTRY[key][0](filtered, options.from_date, options.to_date, context) for key in report_keys]

    issues = run_checks({r.key: r for r in results})
    run_info = {
        "from_date": options.from_date, "to_date": options.to_date, "generated_at": now,
        "reports": list(options.report_keys),
        "filters": [f"{r.field} {r.op} {r.value}" for r in options.filters],
        "preset": options.preset, "excluded_owners_included": options.include_excluded_owners,
        "mask_pii": options.mask_pii, "api_calls": client.call_count, "issues": issues,
        "row_counts": {name: len(getattr(filtered, name)) for name in
                       ("leads_created", "leads_modified", "opportunities", "enrolments", "tasks", "users")},
    }
    return results, run_info


def build_workbook(dataset: Dataset, options: PipelineOptions, settings: Settings, client: LSQClient) -> tuple[bytes, dict]:
    """build_report_results(), then write_workbook(). Makes no API calls except
    final_count.py's live Overdues snapshot (one call per active counselor, via `client`)."""
    results, run_info = build_report_results(dataset, options, settings, client)
    out_path = (Path(options.out_path) if options.out_path
                else OUTPUT_DIR / f"FunnelLens_{options.from_date}_to_{options.to_date}.xlsx")
    data = write_workbook(results, run_info, path=out_path)
    run_info["output_path"] = str(out_path)
    return data, run_info


def run_pipeline(options: PipelineOptions, progress_callback: ProgressCallback | None = None) -> tuple[bytes, dict]:
    settings = load_settings()
    client = LSQClient(settings)
    dataset = fetch_and_normalize(options.from_date, options.to_date, settings, client,
                                   owners=options.owners, progress_callback=progress_callback,
                                   force_refresh=options.force_refresh)
    return build_workbook(dataset, options, settings, client)
