"""Command-line entry point: test-connection, pull, generate, verify, snapshot,
list-reports, list-presets. verify/snapshot are stubs until Phases 8/9.

Errors print a one-line message, not a Python traceback -- pass --debug to see the
traceback instead (main()'s job, not each command's).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from funnellens.extract import fetch_dataset
from funnellens.filters import FilterError, load_presets, parse_filter_string
from funnellens.lsq_client import LSQClient, LSQError
from funnellens.normalize import normalize_dataset
from funnellens.pipeline import PipelineError, PipelineOptions, run_pipeline
from funnellens.reports import REGISTRY
from funnellens.settings import SettingsError, load_settings


def _progress(stage: str, done: int, total: int) -> None:
    print(f"\r{stage}: {done}/{total}", end="", file=sys.stderr, flush=True)
    if done >= total:
        print(file=sys.stderr)


def cmd_test_connection(_args: argparse.Namespace) -> int:
    settings = load_settings()
    LSQClient(settings).test_connection()
    print(f"Connected to {settings.secrets.api_host} successfully.")
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    settings = load_settings()
    client = LSQClient(settings)
    dataset = fetch_dataset(date.fromisoformat(args.from_date), date.fromisoformat(args.to_date),
                             settings, client=client, force_refresh=args.force_refresh)
    normalized = normalize_dataset(dataset, settings)

    for entity in ("leads_created", "leads_modified"):
        df = getattr(normalized, entity)
        print(f"{entity}:")
        counts = df.groupby("ist_date").size() if not df.empty else {}
        for day, count in counts.items():
            print(f"  {day}: {count}")
        print(f"  total: {len(df)}")
    for entity in ("opportunities", "enrolments", "tasks"):
        print(f"{entity}: {len(getattr(normalized, entity))} rows")
    print(f"users: {len(normalized.users)} rows")
    print(f"API calls made: {client.call_count}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    report_keys = list(REGISTRY) if args.reports == ["all"] else args.reports
    filters = [parse_filter_string(text) for text in args.filter]
    options = PipelineOptions(
        from_date=date.fromisoformat(args.from_date), to_date=date.fromisoformat(args.to_date),
        report_keys=report_keys, owners=args.owner, filters=filters, preset=args.preset,
        include_excluded_owners=args.include_excluded_owners, mask_pii=args.mask_pii,
        force_refresh=args.force_refresh, out_path=args.out,
    )
    _, run_info = run_pipeline(options, progress_callback=_progress)

    print(f"Wrote {run_info['output_path']}")
    issues = run_info.get("issues") or []
    if issues:
        print(f"{len(issues)} issue(s) found:")
        for issue in issues:
            print(f"  - {issue}")
    return 0


def cmd_verify(_args: argparse.Namespace) -> int:
    print("verify is available after Phase 8.")
    return 0


def cmd_snapshot(_args: argparse.Namespace) -> int:
    print("snapshot is available after Phase 9.")
    return 0


def cmd_list_reports(_args: argparse.Namespace) -> int:
    for key, (_, title) in REGISTRY.items():
        print(f"{key}: {title}")
    return 0


def cmd_list_presets(_args: argparse.Namespace) -> int:
    presets = load_presets()
    if not presets:
        print("No presets defined in config/presets.yaml.")
        return 0
    for preset in presets:
        print(f"{preset.name} ({len(preset.rules)} rule(s))")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli.py", description="FunnelLens command-line interface")
    parser.add_argument("--debug", action="store_true", help="Show full Python tracebacks on error")
    subparsers = parser.add_subparsers(dest="command", required=True)

    test_connection = subparsers.add_parser("test-connection", help="Verify LeadSquared credentials and host")
    test_connection.set_defaults(func=cmd_test_connection)

    pull = subparsers.add_parser("pull", help="Pull raw data for a date range and print row counts")
    pull.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD, IST")
    pull.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD, IST")
    pull.add_argument("--force-refresh", action="store_true", help="Ignore the cache and refetch everything")
    pull.set_defaults(func=cmd_pull)

    generate = subparsers.add_parser("generate", help="Pull, filter, build reports and write an Excel workbook")
    generate.add_argument("--reports", nargs="+", required=True, metavar="KEY",
                           help=f"Report keys (see list-reports) or 'all'. Choices: {', '.join(REGISTRY)}")
    generate.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD, IST")
    generate.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD, IST")
    generate.add_argument("--owner", action="append", help="Restrict to this counselor (repeatable)")
    generate.add_argument("--filter", action="append", default=[], metavar="RULE",
                           help='A filter rule, e.g. "course in ACCA,CMA" (repeatable)')
    generate.add_argument("--preset", help="Preset name from config/presets.yaml")
    generate.add_argument("--include-excluded-owners", action="store_true")
    generate.add_argument("--mask-pii", action="store_true", help="Redact phone/email in Raw Data")
    generate.add_argument("--force-refresh", action="store_true", help="Ignore the cache and refetch everything")
    generate.add_argument("--out", help="Output .xlsx path (default: output/FunnelLens_<from>_to_<to>.xlsx)")
    generate.set_defaults(func=cmd_generate)

    verify = subparsers.add_parser("verify", help="Compare output against an exported Google Sheet (Phase 8)")
    verify.add_argument("--sheet", required=True, help="Path to the exported Google Sheet .xlsx")
    verify.add_argument("--from", dest="from_date", required=True)
    verify.add_argument("--to", dest="to_date", required=True)
    verify.set_defaults(func=cmd_verify)

    snapshot = subparsers.add_parser("snapshot", help="Save today's stage snapshot (Phase 9)")
    snapshot.set_defaults(func=cmd_snapshot)

    list_reports = subparsers.add_parser("list-reports", help="List available report keys")
    list_reports.set_defaults(func=cmd_list_reports)

    list_presets = subparsers.add_parser("list-presets", help="List presets from config/presets.yaml")
    list_presets.set_defaults(func=cmd_list_presets)

    return parser


_KNOWN_ERRORS = (SettingsError, LSQError, PipelineError, FilterError, ValueError)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except _KNOWN_ERRORS as exc:
        if args.debug:
            raise
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
