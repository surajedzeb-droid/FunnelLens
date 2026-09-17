"""Command-line entry point: generate, verify, snapshot, test-connection, pull.

"test-connection" (Phase 1) and "pull" (Phase 2) are implemented. The rest lands in Phase 6.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from funnellens.extract import fetch_dataset
from funnellens.lsq_client import LSQClient, LSQError
from funnellens.normalize import normalize_dataset
from funnellens.settings import SettingsError, load_settings


def cmd_test_connection(_args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
        client = LSQClient(settings)
        client.test_connection()
    except SettingsError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    except LSQError as exc:
        print(f"LeadSquared connection failed: {exc}", file=sys.stderr)
        return 1
    print(f"Connected to {settings.secrets.api_host} successfully.")
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
        client = LSQClient(settings)
        dataset = fetch_dataset(date.fromisoformat(args.from_date), date.fromisoformat(args.to_date),
                                 settings, client=client, force_refresh=args.force_refresh)
        normalized = normalize_dataset(dataset, settings)
    except SettingsError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    except LSQError as exc:
        print(f"LeadSquared request failed: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Invalid date range: {exc}", file=sys.stderr)
        return 1

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli.py", description="FunnelLens command-line interface")
    subparsers = parser.add_subparsers(dest="command", required=True)

    test_connection = subparsers.add_parser("test-connection", help="Verify LeadSquared credentials and host")
    test_connection.set_defaults(func=cmd_test_connection)

    pull = subparsers.add_parser("pull", help="Pull raw data for a date range and print row counts")
    pull.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD, IST")
    pull.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD, IST")
    pull.add_argument("--force-refresh", action="store_true", help="Ignore the cache and refetch everything")
    pull.set_defaults(func=cmd_pull)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
