from __future__ import annotations

import argparse
from pathlib import Path

from .orchestrator import AnalysisMode, run_analysis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Skywatcher FR24 two-stage image analysis")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run the two-stage workflow")
    run_parser.add_argument("input", type=Path)
    run_parser.add_argument("--output-dir", type=Path, required=True)
    run_parser.add_argument("--mode", choices=[mode.value for mode in AnalysisMode], default=AnalysisMode.STANDARD.value)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "run":
        run = run_analysis(args.input, args.output_dir, AnalysisMode(args.mode))
        print(f"{run.run_id}: complete -> {run.output_dir}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
