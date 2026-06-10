"""
FR24 REVIEW QUEUE BUILDER

Builds a prioritized review queue from the fused OCR event candidates CSV.
Records are ranked by conflict severity (number of conflicting fields) and
confidence.  Images with no region match are included at lower priority.

Outputs
-------
  fr24_fused_review_queue.csv   Overwrite of the review queue with priority
                                scores added. Same format as fr24_ocr_fusion.py
                                output but filtered to rows requiring review.

All output review_status values are candidates only.
Disallowed: confirmed, confirmed_anomaly, confirmed_aircraft_event,
            confirmed_infrastructure.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import List

DISALLOWED_REVIEW_STATUSES = {
    "confirmed",
    "confirmed_anomaly",
    "confirmed_aircraft_event",
    "confirmed_infrastructure",
}

REVIEW_REQUIRED_STATUSES = {
    "fusion_conflict_review",
    "fusion_no_region_match",
    "region_parsed_candidate",
    "region_low_text_review",
    "region_ocr_failed",
    "region_manual_review_required",
    "manual_review_required",
    "low_text_review",
    "parsed_candidate",
}


def _conflict_count(row: dict) -> int:
    cf = row.get("conflict_fields", "")
    if not cf:
        return 0
    return len([x for x in cf.split(",") if x.strip()])


def _priority_score(row: dict) -> float:
    score = 0.0
    conflicts = _conflict_count(row)
    score += conflicts * 10.0
    status = row.get("review_status", "")
    if status == "fusion_conflict_review":
        score += 20.0
    elif status == "fusion_no_region_match":
        score += 5.0
    try:
        conf = float(row.get("confidence", 0) or 0)
        score += conf * 5.0
    except Exception:
        pass
    return round(score, 2)


def build_review_queue(fused_csv: Path, review_csv: Path) -> dict:
    rows: List[dict] = []
    if fused_csv.exists():
        with fused_csv.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

    review_rows = [r for r in rows if r.get("review_status") in REVIEW_REQUIRED_STATUSES]

    for row in review_rows:
        assert row.get("review_status") not in DISALLOWED_REVIEW_STATUSES
        row["priority_score"] = _priority_score(row)
        row["conflict_count"] = _conflict_count(row)

    review_rows.sort(key=lambda r: -float(r.get("priority_score", 0)))

    fallback_fields = ["image_path", "image_name", "review_status", "priority_score", "conflict_count"]
    fieldnames: List[str] = fallback_fields
    if rows:
        fieldnames = list(rows[0].keys())
        for col in ("priority_score", "conflict_count"):
            if col not in fieldnames:
                fieldnames.append(col)

    review_csv.parent.mkdir(parents=True, exist_ok=True)
    with review_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(review_rows)

    return {
        "fused_csv": str(fused_csv),
        "review_csv": str(review_csv),
        "total_fused": len(rows),
        "review_rows": len(review_rows),
        "conflict_rows": sum(1 for r in review_rows if r.get("review_status") == "fusion_conflict_review"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build prioritized FR24 review queue from fused candidates")
    parser.add_argument(
        "--fused-csv",
        default="data/_manifests/fr24_audit/fr24_fused_event_candidates.csv",
    )
    parser.add_argument(
        "--review-csv",
        default="data/_manifests/fr24_audit/fr24_fused_review_queue.csv",
    )
    args = parser.parse_args()
    summary = build_review_queue(Path(args.fused_csv), Path(args.review_csv))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
