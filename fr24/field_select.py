"""
FR24 FIELD SELECTION

Selects candidate fields from fused OCR rows while preserving source values.
Disagreements remain visible and are routed to review.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import List

FIELD_SELECT_VERSION = "fr24_field_select_v0.1.0"
SELECT_FIELDS = [
    "callsign_or_label",
    "operator",
    "aircraft_type",
    "registration",
    "origin_code",
    "destination_code",
    "barometric_altitude_ft",
    "ground_speed_mph",
    "flight_status",
    "elapsed_departed",
    "elapsed_arrived",
    "playback_date",
    "playback_time",
    "playback_timezone",
]

REGION_PREFERRED_FIELDS = {
    "callsign_or_label",
    "operator",
    "aircraft_type",
    "registration",
    "barometric_altitude_ft",
    "ground_speed_mph",
}
TIMELINE_PREFERRED_FIELDS = {
    "playback_date",
    "playback_time",
    "playback_timezone",
    "elapsed_departed",
    "elapsed_arrived",
    "flight_status",
}


def read_csv(path: Path) -> List[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return list(csv.DictReader(path.open(encoding="utf-8")))


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


def values_disagree(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return a.strip().lower() != b.strip().lower()


def as_float(value: object) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def choose_field(row: dict, field: str) -> tuple[str, str, str]:
    wi = row.get(f"{field}_wi", "")
    region = row.get(f"{field}_region", "")
    region_name = row.get("region_name", "")
    wi_conf = as_float(row.get("whole_confidence"))
    region_conf = as_float(row.get("region_confidence"))

    if values_disagree(wi, region):
        return "", "disagreement", "field_disagreement_review"
    if wi and not region:
        return wi, "whole_image", "selected_candidate"
    if region and not wi:
        return region, f"region:{region_name or 'unknown'}", "selected_candidate"
    if not wi and not region:
        return "", "missing", "missing_field"

    if field in REGION_PREFERRED_FIELDS and region_name == "right_panel":
        return region, f"region:{region_name}", "selected_candidate"
    if field in TIMELINE_PREFERRED_FIELDS and region_name == "bottom_timeline":
        return region, f"region:{region_name}", "selected_candidate"
    if region_conf > wi_conf:
        return region, f"region:{region_name or 'unknown'}", "selected_candidate"
    return wi, "whole_image", "selected_candidate"


def select_row(row: dict) -> dict:
    out = dict(row)
    disagreements = []
    missing = []
    selected_sources = []

    for field in SELECT_FIELDS:
        value, source, status = choose_field(row, field)
        out[field] = value
        out[f"{field}_selected_source"] = source
        out[f"{field}_selection_status"] = status
        if status == "field_disagreement_review":
            disagreements.append(field)
        elif status == "missing_field":
            missing.append(field)
        elif value:
            selected_sources.append(source)

    if disagreements:
        out["review_status"] = "field_disagreement_review"
        out["selection_status"] = "field_disagreement_review"
    elif row.get("review_status") in {"fusion_conflict_review", "manual_review_required", "region_only_review"}:
        out["selection_status"] = "selected_with_review_required"
    else:
        out["selection_status"] = "selected_candidate"

    out["selected_field_disagreements"] = ";".join(disagreements)
    out["missing_selected_fields"] = ";".join(missing)
    out["selected_source_set"] = ";".join(sorted(set(s for s in selected_sources if s and s != "missing")))
    out["field_select_version"] = FIELD_SELECT_VERSION
    out["confirmation_status"] = "not_confirmed"
    return out


def run(input_csv: Path, output_csv: Path, review_csv: Path, summary_json: Path) -> dict:
    rows = read_csv(input_csv)
    selected = [select_row(r) for r in rows]
    write_csv(output_csv, selected)
    review_rows = [r for r in selected if r.get("selection_status") != "selected_candidate"]
    write_csv(review_csv, review_rows)
    summary = {
        "input_csv": str(input_csv),
        "output_csv": str(output_csv),
        "review_csv": str(review_csv),
        "input_rows": len(rows),
        "selected_rows": len(selected),
        "review_rows": len(review_rows),
        "selection_status_counts": dict(Counter(r.get("selection_status", "") for r in selected)),
        "review_status_counts": dict(Counter(r.get("review_status", "") for r in selected)),
        "field_select_version": FIELD_SELECT_VERSION,
        "policy": "candidate_only_no_auto_confirmation",
    }
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Select candidate fields from FR24 fused OCR rows")
    parser.add_argument("--input-csv", default="data/_manifests/fr24_audit/fr24_fused_event_candidates_deduped.csv")
    parser.add_argument("--output-csv", default="data/_manifests/fr24_audit/fr24_event_candidates_selected.csv")
    parser.add_argument("--review-csv", default="data/_manifests/fr24_audit/fr24_field_selection_review_queue.csv")
    parser.add_argument("--summary-json", default="data/_manifests/fr24_audit/fr24_field_selection_summary.json")
    args = parser.parse_args()
    summary = run(Path(args.input_csv), Path(args.output_csv), Path(args.review_csv), Path(args.summary_json))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
