"""Command line entry point for SATIM route findings."""

from __future__ import annotations

import argparse

from .report import run_analysis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate read-only SATIM route findings outputs.")
    parser.add_argument("--input", required=True, help="Directory containing SATIM CSV ledgers")
    parser.add_argument("--output", required=True, help="Directory for generated route findings outputs")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    summary = run_analysis(args.input, args.output)
    print(
        "SATIM route findings complete: "
        f"route_clusters={summary['route_clusters']} "
        f"fn_candidates={summary['fn_candidates']} "
        f"review_rows={summary['review_rows']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
