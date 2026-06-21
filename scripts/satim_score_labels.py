#!/usr/bin/env python3
"""Score a SATIM calibration set's labels and emit review artifacts.

Loads a calibration set, applies the conservative false-positive scoring and
promotion bands from ``satim_calibration``, and writes:

  * ``<out-dir>/<calibration_id>/scored_labels.csv`` -- one row per marked label
  * ``<out-dir>/<calibration_id>/summary.json``      -- frontend-ready summary

Optionally also writes the summary JSON to ``--frontend-out`` so the vendored
React app can render it as a static asset (no backend required).

Usage::

    python scripts/satim_score_labels.py data/satim_calibration/moca_fr24_2025
    python scripts/satim_score_labels.py data/satim_calibration/moca_fr24_2025 \\
        --frontend-out frontend/public/satim/moca_fr24_2025.summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satim_calibration import load_calibration_set, score_calibration_set  # noqa: E402

SCORED_LABEL_COLUMNS = (
    "image_id",
    "frame",
    "marker_type",
    "feature_class",
    "false_positive_class",
    "resolved_false_positive_class",
    "resolution_status",
    "raw_confidence",
    "adjustment",
    "adjusted_score",
    "decision",
    "unknown_false_positive_class",
    "frame_recurrence",
    "notes",
)


def write_scored_csv(path: Path, labels: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCORED_LABEL_COLUMNS)
        writer.writeheader()
        for row in labels:
            writer.writerow({col: row.get(col, "") for col in SCORED_LABEL_COLUMNS})


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score SATIM calibration labels")
    parser.add_argument("set_dir", help="Calibration set directory")
    parser.add_argument(
        "--out-dir",
        default="exports/satim_calibration",
        help="Base output directory (default: exports/satim_calibration)",
    )
    parser.add_argument(
        "--frontend-out",
        default=None,
        help="Optional path to also write the summary JSON (e.g. frontend/public/satim/<id>.summary.json)",
    )
    args = parser.parse_args(argv)

    set_dir = Path(args.set_dir)
    if not (set_dir / "registry_entry.yaml").exists():
        print(f"ERROR: {set_dir} is not a calibration set (no registry_entry.yaml)")
        return 1

    calibration_set = load_calibration_set(set_dir)
    summary = score_calibration_set(calibration_set)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()

    out_dir = Path(args.out_dir) / (calibration_set.calibration_id or set_dir.name)
    write_scored_csv(out_dir / "scored_labels.csv", summary["labels"])
    write_json(out_dir / "summary.json", summary)

    if args.frontend_out:
        write_json(Path(args.frontend_out), summary)

    print(f"Scored {summary['counts']['labels']} label(s) for {summary['calibration_id']}")
    print(f"  decisions: {summary['decision_breakdown']}")
    print(f"  mean adjusted score: {summary['score_summary']['mean_adjusted']}")
    print(f"  wrote: {out_dir / 'scored_labels.csv'}")
    print(f"  wrote: {out_dir / 'summary.json'}")
    if args.frontend_out:
        print(f"  wrote: {args.frontend_out}")
    for warning in summary["warnings"]:
        print(f"  WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
