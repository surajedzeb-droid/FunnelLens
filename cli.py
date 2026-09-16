"""Command-line entry point: generate, verify, snapshot, test-connection.

Only "test-connection" is implemented so far (Phase 1). The rest lands in Phase 6.
"""

from __future__ import annotations

import argparse
import sys

from funnellens.lsq_client import LSQClient, LSQError
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli.py", description="FunnelLens command-line interface")
    subparsers = parser.add_subparsers(dest="command", required=True)

    test_connection = subparsers.add_parser("test-connection", help="Verify LeadSquared credentials and host")
    test_connection.set_defaults(func=cmd_test_connection)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
