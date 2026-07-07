"""Canonical GATIM runner."""
from __future__ import annotations

import argparse
from pathlib import Path

from tools.gatim.core.classifier import apply_classification
from tools.gatim.core.dedupe import assign_clusters
from tools.gatim.core.normalizer import normalize_many
from tools.gatim.exports.csv_exporter import write_ledger, write_review_queue
from tools.gatim.exports.geocode_queue import write_geocode_queue
from tools.gatim.exports.geojson_exporter import write_geojson

DEFAULT_FILES = ["uap.csv", "access.csv", "ilap.csv", "poi.csv", "recon.csv", "anomaly.csv"]


def build(input_dir: Path, out_dir: Path, dedupe_radius_m: float = 5.0, files: list[str] | None = None) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = normalize_many(input_dir / name for name in (files or DEFAULT_FILES))
    rows = assign_clusters(rows, radius_m=dedupe_radius_m)
    rows = apply_classification(rows)
    write_ledger(rows, out_dir / "GATIM_CALIBRATION_LEDGER_v1.csv")
    write_review_queue(rows, out_dir / "GATIM_REVIEW_QUEUE_v1.csv")
    write_geocode_queue(rows, out_dir / "GATIM_GEOCODE_QUEUE_v1.csv")
    write_geojson(rows, out_dir / "GATIM_CANDIDATES_v1.geojson")
    write_geojson([row for row in rows if row.coord_status == "direct"], out_dir / "GATIM_REVIEW_QUEUE_v1.geojson")
    return {
        "rows": len(rows),
        "direct": sum(row.coord_status == "direct" for row in rows),
        "needs_geocode": sum(row.coord_status == "needs_geocode" for row in rows),
        "missing": sum(row.coord_status == "missing" for row in rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build GATIM ledgers and exports.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--dedupe-radius-m", type=float, default=5.0)
    parser.add_argument("--files", nargs="*", default=None)
    args = parser.parse_args()
    metrics = build(Path(args.input_dir), Path(args.out_dir), args.dedupe_radius_m, args.files)
    print(" ".join(f"{key}={value}" for key, value in metrics.items()))


if __name__ == "__main__":
    main()
