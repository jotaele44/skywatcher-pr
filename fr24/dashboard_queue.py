"""
FR24 DASHBOARD REVIEW QUEUE

Builds a review-first dashboard queue from FR24 selected candidate outputs and
review-gated CSVs. Each row is ranked by review tier so a dashboard reviewer
can work the highest-priority items first. This queue does not confirm events.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import List

DASHBOARD_QUEUE_VERSION = "fr24_dashboard_queue_v0.1.1"

TIER_FIELD_DISAGREEMENT = 1
TIER_FUSION_CONFLICT = 2
TIER_MANUAL_REVIEW = 3
TIER_DUPLICATE_REVIEW = 4
TIER_METADATA_GAP = 5
TIER_OCR_FAILURE = 6

TIER_BASE_SCORE = {
    TIER_FIELD_DISAGREEMENT: 100,
    TIER_FUSION_CONFLICT: 80,
    TIER_MANUAL_REVIEW: 60,
    TIER_DUPLICATE_REVIEW: 40,
    TIER_METADATA_GAP: 25,
    TIER_OCR_FAILURE: 15,
}

ALLOWED_QUEUE_STATUSES = (
    "dashboard_review_open",
    "dashboard_review_deferred",
    "dashboard_review_rejected",
    "dashboard_review_accepted_after_manual_review",
)

OCR_FAILURE_STATUSES = {
    "region_ocr_failed",
    "region_low_text_review",
    "low_text_review",
    "failed",
}

PROHIBITED_LABELS = {
    "confirmed",
    "confirmed_aircraft_event",
    "confirmed_anomaly",
    "confirmed_route",
    "verified_event",
    "validated_aircraft_event",
}


def read_csv(path: Path) -> List[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return list(csv.DictReader(path.open(encoding="utf-8")))


def has_prohibited_label(row: dict) -> bool:
    for key in ("confirmation_status", "dedup_status", "selection_status", "review_status", "status"):
        value = (row.get(key) or "").strip().lower()
        if value in PROHIBITED_LABELS:
            return True
    return False


def as_int(value: object) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


REVIEW_STATUS_TIER = {
    "field_disagreement_review": TIER_FIELD_DISAGREEMENT,
    "fusion_conflict_review": TIER_FUSION_CONFLICT,
    "manual_review_required": TIER_MANUAL_REVIEW,
    "metadata_gap": TIER_METADATA_GAP,
}

SELECTION_STATUS_TIER = {
    "field_disagreement_review": TIER_FIELD_DISAGREEMENT,
    "selected_with_review_required": TIER_MANUAL_REVIEW,
}


def classify_field_review(row: dict) -> int:
    candidates = []
    review_tier = REVIEW_STATUS_TIER.get((row.get("review_status") or "").strip())
    if review_tier is not None:
        candidates.append(review_tier)
    selection_tier = SELECTION_STATUS_TIER.get((row.get("selection_status") or "").strip())
    if selection_tier is not None:
        candidates.append(selection_tier)
    return min(candidates) if candidates else TIER_MANUAL_REVIEW


def classify_selected_row(row: dict) -> int | None:
    return REVIEW_STATUS_TIER.get((row.get("review_status") or "").strip())


def priority_score(row: dict, tier: int) -> int:
    score = TIER_BASE_SCORE.get(tier, 0)
    score += min(20, as_int(row.get("conflict_count")) * 5)
    if (row.get("selected_field_disagreements") or "").strip():
        score += 5
    return score


def enrich_row(row: dict, tier: int, source: str) -> dict:
    out = dict(row)
    out["queue_source"] = source
    out["priority_tier"] = tier
    out["priority_score"] = priority_score(row, tier)
    out["queue_status"] = "dashboard_review_open"
    out["confirmation_status"] = "not_confirmed"
    out["dashboard_queue_version"] = DASHBOARD_QUEUE_VERSION
    return out


def row_identity(row: dict) -> str:
    """Return the strongest available row identity without collapsing blanks."""
    for field in ("image_path", "image_name", "candidate_id"):
        value = (row.get(field) or "").strip()
        if value:
            return f"{field}::{value}"
    # Last-resort fallback uses stable review metadata to avoid one giant empty-key bucket.
    return "unidentified::" + "::".join(
        [
            (row.get("queue_source") or "").strip(),
            (row.get("review_status") or "").strip(),
            (row.get("selection_status") or "").strip(),
            (row.get("dedup_group_id") or "").strip(),
            (row.get("_source_csv") or "").strip(),
        ]
    )


def queue_dedup_key(row: dict) -> tuple:
    return (row_identity(row), row.get("queue_source", ""))


def collect_queue(
    selected_rows: List[dict],
    field_review_rows: List[dict],
    duplicate_review_rows: List[dict],
    ocr_error_rows: List[dict],
) -> List[dict]:
    queue: List[dict] = []
    captured_images: set[str] = set()

    for row in field_review_rows:
        if has_prohibited_label(row):
            continue
        tier = classify_field_review(row)
        queue.append(enrich_row(row, tier, "field_selection_review"))
        identity = row_identity(row)
        if identity:
            captured_images.add(identity)

    for row in duplicate_review_rows:
        if has_prohibited_label(row):
            continue
        queue.append(enrich_row(row, TIER_DUPLICATE_REVIEW, "fused_duplicate_review"))

    for row in selected_rows:
        if has_prohibited_label(row):
            continue
        if row_identity(row) in captured_images:
            continue
        tier = classify_selected_row(row)
        if tier is None:
            continue
        queue.append(enrich_row(row, tier, "selected_review"))

    for row in ocr_error_rows:
        if has_prohibited_label(row):
            continue
        status = (row.get("review_status") or row.get("status") or "").strip()
        if status not in OCR_FAILURE_STATUSES:
            continue
        queue.append(enrich_row(row, TIER_OCR_FAILURE, "ocr_failure"))

    seen: set[tuple] = set()
    deduped: List[dict] = []
    for row in queue:
        key = queue_dedup_key(row)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    deduped.sort(key=lambda r: (-int(r.get("priority_score") or 0), int(r.get("priority_tier") or 9), r.get("image_name", "")))
    return deduped


def write_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({k for row in rows for k in row.keys()})
    preferred_head = [
        "priority_score", "priority_tier", "queue_source", "queue_status",
        "candidate_id", "image_path", "image_name",
        "review_status", "selection_status", "dedup_status",
        "confirmation_status", "dashboard_queue_version",
    ]
    ordered = [c for c in preferred_head if c in fieldnames] + [c for c in fieldnames if c not in preferred_head]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ordered, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in ordered})


def run(
    selected_csv: Path,
    field_review_csv: Path,
    duplicate_review_csv: Path,
    ocr_error_csv: Path,
    output_csv: Path,
    summary_json: Path,
) -> dict:
    selected_rows = read_csv(selected_csv)
    field_review_rows = read_csv(field_review_csv)
    duplicate_review_rows = read_csv(duplicate_review_csv)
    ocr_error_rows = read_csv(ocr_error_csv) if ocr_error_csv.exists() else []

    queue = collect_queue(selected_rows, field_review_rows, duplicate_review_rows, ocr_error_rows)
    write_csv(output_csv, queue)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selected_csv": str(selected_csv),
        "field_review_csv": str(field_review_csv),
        "duplicate_review_csv": str(duplicate_review_csv),
        "ocr_error_csv": str(ocr_error_csv),
        "ocr_error_csv_present": ocr_error_csv.exists(),
        "output_csv": str(output_csv),
        "input_row_counts": {
            "selected": len(selected_rows),
            "field_review": len(field_review_rows),
            "duplicate_review": len(duplicate_review_rows),
            "ocr_error": len(ocr_error_rows),
        },
        "queue_rows": len(queue),
        "tier_counts": dict(Counter(r.get("priority_tier") for r in queue)),
        "source_counts": dict(Counter(r.get("queue_source", "") for r in queue)),
        "review_status_counts": dict(Counter(r.get("review_status", "") for r in queue)),
        "allowed_queue_statuses": list(ALLOWED_QUEUE_STATUSES),
        "dashboard_queue_version": DASHBOARD_QUEUE_VERSION,
        "policy": "candidate_only_no_auto_confirmation",
    }
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build FR24 dashboard review queue")
    parser.add_argument("--selected-csv", default="data/_manifests/fr24_audit/fr24_event_candidates_selected.csv")
    parser.add_argument("--field-review-csv", default="data/_manifests/fr24_audit/fr24_field_selection_review_queue.csv")
    parser.add_argument("--duplicate-review-csv", default="data/_manifests/fr24_audit/fr24_fused_duplicate_review_queue.csv")
    parser.add_argument("--ocr-error-csv", default="data/_manifests/fr24_audit/fr24_batch_error_queue.csv")
    parser.add_argument("--output-csv", default="data/_manifests/fr24_audit/fr24_dashboard_review_queue.csv")
    parser.add_argument("--summary-json", default="data/_manifests/fr24_audit/fr24_dashboard_queue_summary.json")
    args = parser.parse_args()
    summary = run(
        Path(args.selected_csv),
        Path(args.field_review_csv),
        Path(args.duplicate_review_csv),
        Path(args.ocr_error_csv),
        Path(args.output_csv),
        Path(args.summary_json),
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
