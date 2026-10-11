"""Talos CLI entry point."""

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="talos",
        description="Resolves records to legal entities, links entities into groups, and computes group exposure entirely inside Exasol.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    subparsers.add_parser("probe", help="Run capability probe against Exasol Nano")
    subparsers.add_parser("init", help="Initialize Exasol users, roles, and schemas")
    subparsers.add_parser("reset", help="Drop and re-initialize all Talos schemas")
    subparsers.add_parser("match", help="Run entity resolution matching pipeline")
    subparsers.add_parser("serve", help="Start web console on 127.0.0.1:8000")
    subparsers.add_parser("demo", help="End-to-end demo execution")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    print(f"Talos command '{args.command}' invoked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
