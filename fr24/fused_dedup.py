"""
FR24 FUSED CANDIDATE DEDUP

Deduplicates fused OCR candidate rows across one or more CSV outputs. This is a
post-fusion hygiene layer: it keeps one preferred candidate per image key and
routes duplicate rows to a duplicate queue. It does not confirm events.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, List

DEDUP_VERSION = "fr24_fused_dedup_v0.1.0"

STATUS_RANK = {
    "fused_candidate": 0,
    "manual_review_required": 1,
    "fusion_conflict_review": 2,
    "region_only_review": 3,
}


def read_csv(path: Path) -> List[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    for row in rows:
        row["_source_csv"] = str(path)
    return rows


def write_csv(path: Path, rows: List[dict], fieldnames: List[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not fieldnames:
        fieldnames = sorted({k for row in rows for k in row.keys()}) if rows else []
    if not fieldnames:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def dedup_key(row: dict) -> str:
    image_path = (row.get("image_path") or "").strip()
    if image_path:
        return f"image_path::{image_path}"
    image_name = (row.get("image_name") or "").strip()
    if image_name:
        return f"image_name::{image_name}"
    return f"candidate_id::{row.get('candidate_id', '')}"


def as_float(value: object) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def as_int(value: object) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def row_quality(row: dict) -> tuple:
    """Lower tuple wins.

    Prefer rows with fewer conflicts and higher available OCR confidence, while
    still preserving review-gated rows in the duplicate queue.
    """
    review_status = row.get("review_status", "")
    status_rank = STATUS_RANK.get(review_status, 9)
    conflict_count = as_int(row.get("conflict_count"))
    confidence = max(as_float(row.get("whole_confidence")), as_float(row.get("region_confidence")))
    source_csv = row.get("_source_csv", "")
    return (conflict_count, status_rank, -confidence, source_csv, row.get("candidate_id", ""))


def dedupe_rows(rows: Iterable[dict]) -> tuple[List[dict], List[dict], dict]:
    groups: dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        groups[dedup_key(row)].append(row)

    kept: List[dict] = []
    duplicates: List[dict] = []
    for group_index, (key, group_rows) in enumerate(sorted(groups.items()), 1):
        ranked = sorted(group_rows, key=row_quality)
        winner = dict(ranked[0])
        winner["dedup_key"] = key
        winner["dedup_group_id"] = f"dedup_group_{group_index:06d}"
        winner["duplicate_count"] = len(ranked) - 1
        winner["dedup_status"] = "dedup_kept_primary"
        winner["dedup_version"] = DEDUP_VERSION
        winner["confirmation_status"] = "not_confirmed"
        kept.append(winner)

        for loser in ranked[1:]:
            out = dict(loser)
            out["dedup_key"] = key
            out["dedup_group_id"] = winner["dedup_group_id"]
            out["duplicate_count"] = len(ranked) - 1
            out["dedup_status"] = "dedup_duplicate_review"
            out["dedup_version"] = DEDUP_VERSION
            out["confirmation_status"] = "not_confirmed"
            duplicates.append(out)

    summary = {
        "input_rows": sum(len(v) for v in groups.values()),
        "deduped_rows": len(kept),
        "duplicate_rows": len(duplicates),
        "duplicate_groups": sum(1 for v in groups.values() if len(v) > 1),
        "review_status_counts": dict(Counter(r.get("review_status", "") for r in kept)),
        "dedup_version": DEDUP_VERSION,
        "policy": "candidate_only_no_auto_confirmation",
    }
    return kept, duplicates, summary


def run(input_csvs: List[Path], output_csv: Path, duplicates_csv: Path, summary_json: Path) -> dict:
    rows: List[dict] = []
    for path in input_csvs:
        rows.extend(read_csv(path))
    kept, duplicates, summary = dedupe_rows(rows)
    fieldnames = sorted({k for row in kept + duplicates for k in row.keys()})
    write_csv(output_csv, kept, fieldnames)
    write_csv(duplicates_csv, duplicates, fieldnames)
    summary.update({
        "input_csvs": [str(p) for p in input_csvs],
        "output_csv": str(output_csv),
        "duplicates_csv": str(duplicates_csv),
    })
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Deduplicate FR24 fused OCR candidate CSVs")
    parser.add_argument("--input-csv", action="append", required=True, help="Input fused candidate CSV; may be repeated")
    parser.add_argument("--output-csv", default="data/_manifests/fr24_audit/fr24_fused_event_candidates_deduped.csv")
    parser.add_argument("--duplicates-csv", default="data/_manifests/fr24_audit/fr24_fused_duplicate_review_queue.csv")
    parser.add_argument("--summary-json", default="data/_manifests/fr24_audit/fr24_fused_dedup_summary.json")
    args = parser.parse_args()
    summary = run([Path(p) for p in args.input_csv], Path(args.output_csv), Path(args.duplicates_csv), Path(args.summary_json))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
