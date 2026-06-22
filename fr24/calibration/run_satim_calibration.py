"""Aggregate SATIM layer calibration reports into one calibration_report.json."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from .models import merge_layer_reports


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge SATIM L1-L5 layer reports")
    parser.add_argument("--l1")
    parser.add_argument("--l2")
    parser.add_argument("--l3")
    parser.add_argument("--l4")
    parser.add_argument("--l5")
    parser.add_argument("--output", default="reports/satim/calibration_report.json")
    args = parser.parse_args()
    paths: List[str] = [p for p in (args.l1, args.l2, args.l3, args.l4, args.l5) if p]
    if not paths:
        raise SystemExit("at least one --l1/--l2/--l3/--l4/--l5 report path is required")
    merge_layer_reports(paths, Path(args.output))


if __name__ == "__main__":
    main()
