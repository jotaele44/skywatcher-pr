"""GATIM command-line runner for runtime CSV exports."""
from __future__ import annotations

import argparse
from pathlib import Path

from .gatim_classifier import apply_classification
from .gatim_dedupe import assign_clusters
from .gatim_normalizer import normalize_many, write_ledger
from .gatim_review_queue import write_review_queue

DEFAULT_FILES = [
    "UAP.csv",
    "Narnia Roads.csv",
    "DUMBs.csv",
    "What’s Here_.csv",
    "Recon.csv",
    "Map Anomalies.csv",
]


def build(input_dir: Path, out_dir: Path, dedupe_radius_m: float = 5.0, files: list[str] | None = None) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    selected = files or DEFAULT_FILES
    rows = normalize_many(input_dir / name for name in selected)
    rows = assign_clusters(rows, radius_m=dedupe_radius_m)
    rows = apply_classification(rows)
    write_ledger(rows, out_dir / "GATIM_CALIBRATION_LEDGER_v1.csv")
    write_review_queue(rows, out_dir / "GATIM_REVIEW_QUEUE_v1.csv")
    return {
        "rows": len(rows),
        "direct": sum(row.coord_status == "direct" for row in rows),
        "needs_geocode": sum(row.coord_status == "needs_geocode" for row in rows),
        "missing": sum(row.coord_status == "missing" for row in rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build GATIM calibration ledger and review queue.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--dedupe-radius-m", type=float, default=5.0)
    parser.add_argument("--files", nargs="*", default=None)
    args = parser.parse_args()
    metrics = build(Path(args.input_dir), Path(args.out_dir), args.dedupe_radius_m, args.files)
    print(" ".join(f"{key}={value}" for key, value in metrics.items()))


if __name__ == "__main__":
    main()
