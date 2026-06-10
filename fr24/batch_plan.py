"""
FR24 FULL-CORPUS BATCH PLANNER

Creates deterministic batch plans from an OCR-safe FR24 manifest. This planner
only writes CSV/JSON planning artifacts. It does not OCR images and does not
modify source files.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import List

DEFAULT_BATCH_SIZE = 250


def load_manifest(path: Path) -> List[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def priority_rank(row: dict) -> tuple:
    review_status = row.get("review_status", "")
    match_band = row.get("match_band", "")
    resolved = row.get("resolved_status", "")
    if resolved == "matched_primary" and match_band == "strong" and review_status == "sidecar_linked":
        tier = 0
    elif resolved == "matched_primary" and match_band == "reviewable":
        tier = 1
    elif resolved == "matched_primary" and match_band == "weak":
        tier = 2
    elif review_status == "metadata_gap":
        tier = 3
    else:
        tier = 4
    return (tier, row.get("image_name", ""), row.get("image_path", ""))


def batch_label(index: int) -> str:
    return f"fr24_batch_{index:04d}"


def build_plan(rows: List[dict], batch_size: int = DEFAULT_BATCH_SIZE, max_images: int = 0) -> List[dict]:
    eligible = [r for r in rows if r.get("ocr_status", "eligible") == "eligible"]
    eligible = sorted(eligible, key=priority_rank)
    if max_images > 0:
        eligible = eligible[:max_images]

    planned: List[dict] = []
    for idx, row in enumerate(eligible):
        batch_index = idx // batch_size + 1
        out = dict(row)
        out["batch_id"] = batch_label(batch_index)
        out["batch_index"] = batch_index
        out["batch_position"] = idx % batch_size + 1
        out["planner_status"] = "planned_candidate"
        out["confirmation_status"] = "not_confirmed"
        planned.append(out)
    return planned


def write_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_plan(manifest_csv: Path, output_dir: Path, batch_size: int = DEFAULT_BATCH_SIZE, max_images: int = 0) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = load_manifest(manifest_csv)
    planned = build_plan(rows, batch_size, max_images)

    plan_csv = output_dir / "fr24_full_corpus_batch_plan.csv"
    summary_json = output_dir / "fr24_full_corpus_batch_plan_summary.json"
    write_csv(plan_csv, planned)

    batch_counts = Counter(r["batch_id"] for r in planned)
    review_counts = Counter(r.get("review_status", "") for r in planned)
    band_counts = Counter(r.get("match_band", "") for r in planned)
    resolved_counts = Counter(r.get("resolved_status", "") for r in planned)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_csv": str(manifest_csv),
        "total_manifest_rows": len(rows),
        "planned_rows": len(planned),
        "batch_size": batch_size,
        "batch_count": ceil(len(planned) / batch_size) if batch_size else 0,
        "batch_counts": dict(batch_counts),
        "review_status_counts": dict(review_counts),
        "match_band_counts": dict(band_counts),
        "resolved_status_counts": dict(resolved_counts),
        "plan_csv": str(plan_csv),
        "policy": "planning_only_candidate_records_no_auto_confirmation",
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Create FR24 full-corpus OCR batch plan")
    parser.add_argument("--manifest", default="data/_manifests/fr24_audit/fr24_manifest_with_sidecars.csv")
    parser.add_argument("--output-dir", default="data/_manifests/fr24_audit")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-images", type=int, default=0)
    args = parser.parse_args()
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be greater than zero")
    print(json.dumps(run_plan(Path(args.manifest), Path(args.output_dir), args.batch_size, args.max_images), indent=2))


if __name__ == "__main__":
    main()
