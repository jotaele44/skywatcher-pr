"""
FR24 OCR FUSION

Fuses whole-image OCR parsed events with region-level OCR parsed events.

Matching key: image_path

For each matched image the fuser compares six key fields side-by-side and
flags any field-level conflict where both sources supply a non-empty,
non-matching value. Conflicting records go to review; non-conflicting records
are promoted to "fused_candidate".

No confirmed labels are emitted. Fused values are candidates only.

Inputs
------
  --whole-image-csv   fr24_ocr_parsed_events_probe_50.csv (from fr24_ocr_parse.py)
  --region-csv        fr24_region_parsed_events.csv (from fr24_region_parse.py)

Outputs
-------
  --output-csv        fr24_fused_event_candidates.csv
  --review-csv        fr24_fused_review_queue.csv

Column layout in output CSV:
  provenance from whole-image row (all original columns prefixed where
  needed), then per-field side-by-side pairs, then:
    conflict_fields   comma-separated list of field names with conflicts
    region_source_count   number of region rows fused for this image
    review_status     "fused_candidate" | "fusion_conflict_review" |
                      "fusion_no_region_match" | "fusion_region_only"
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

KEY_FIELDS = [
    "callsign_or_label",
    "registration",
    "aircraft_type",
    "barometric_altitude_ft",
    "ground_speed_mph",
    "origin_code",
    "destination_code",
]

DISALLOWED_REVIEW_STATUSES = {"confirmed", "confirmed_anomaly", "confirmed_aircraft_event", "confirmed_infrastructure"}

REGION_FIELD_PREFERENCE = {
    "callsign_or_label": ["callsign"],
    "barometric_altitude_ft": ["altitude", "panel"],
    "ground_speed_mph": ["speed", "panel"],
    "origin_code": ["route", "panel"],
    "destination_code": ["route", "panel"],
    "registration": ["panel"],
    "aircraft_type": ["panel"],
}


def _best_region_value(field: str, region_rows: List[dict]) -> str:
    preferred = REGION_FIELD_PREFERENCE.get(field, ["panel"])
    for pref_type in preferred:
        for row in region_rows:
            if row.get("region_type") == pref_type and row.get(field, "").strip():
                return row[field].strip()
    for row in region_rows:
        if row.get(field, "").strip():
            return row[field].strip()
    return ""


def _conflict(wi_val: str, region_val: str) -> bool:
    return bool(wi_val and region_val and wi_val.strip() != region_val.strip())


def fuse_records(
    wi_rows: List[dict],
    region_rows_by_image: Dict[str, List[dict]],
) -> List[dict]:
    fused = []
    seen_images = set()

    for wi_row in wi_rows:
        img = wi_row.get("image_path", "")
        seen_images.add(img)
        region_rows = region_rows_by_image.get(img, [])

        out = dict(wi_row)
        conflict_fields: List[str] = []

        for field in KEY_FIELDS:
            wi_val = wi_row.get(field, "").strip() if wi_row.get(field) else ""
            region_val = _best_region_value(field, region_rows)

            out[f"{field}_wi"] = wi_val
            out[f"{field}_region"] = region_val

            if _conflict(wi_val, region_val):
                conflict_fields.append(field)

        out["conflict_fields"] = ",".join(conflict_fields)
        out["region_source_count"] = len(region_rows)

        if conflict_fields:
            out["review_status"] = "fusion_conflict_review"
        elif not region_rows:
            out["review_status"] = "fusion_no_region_match"
        else:
            out["review_status"] = "fused_candidate"

        assert out["review_status"] not in DISALLOWED_REVIEW_STATUSES
        fused.append(out)

    for img, region_rows in region_rows_by_image.items():
        if img in seen_images:
            continue
        representative = region_rows[0]
        out = {
            "image_path": img,
            "image_name": representative.get("image_name", ""),
            "sidecar_path": representative.get("sidecar_path", ""),
            "sidecar_title": representative.get("sidecar_title", ""),
            "match_band": representative.get("match_band", ""),
            "resolved_status": representative.get("resolved_status", ""),
        }
        for field in KEY_FIELDS:
            out[f"{field}_wi"] = ""
            out[f"{field}_region"] = _best_region_value(field, region_rows)
        out["conflict_fields"] = ""
        out["region_source_count"] = len(region_rows)
        out["review_status"] = "fusion_region_only"
        fused.append(out)

    return fused


def _derive_output_fieldnames(wi_rows: List[dict]) -> List[str]:
    base = list(wi_rows[0].keys()) if wi_rows else [
        "image_path", "image_name", "sidecar_path", "sidecar_title",
        "match_band", "resolved_status",
    ]
    existing = set(base)
    extra = []
    for field in KEY_FIELDS:
        for suffix in ("_wi", "_region"):
            col = f"{field}{suffix}"
            if col not in existing:
                extra.append(col)
    extra += ["conflict_fields", "region_source_count", "review_status"]
    final = []
    seen = set()
    for col in base + extra:
        if col not in seen:
            final.append(col)
            seen.add(col)
    return final


def run_fusion(
    wi_csv: Path,
    region_csv: Path,
    output_csv: Path,
    review_csv: Path,
) -> dict:
    wi_rows: List[dict] = []
    if wi_csv.exists():
        with wi_csv.open(encoding="utf-8") as f:
            wi_rows = list(csv.DictReader(f))

    region_rows_by_image: Dict[str, List[dict]] = defaultdict(list)
    if region_csv.exists():
        with region_csv.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                region_rows_by_image[row.get("image_path", "")].append(row)

    fused = fuse_records(wi_rows, region_rows_by_image)
    fieldnames = _derive_output_fieldnames(wi_rows)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    review_csv.parent.mkdir(parents=True, exist_ok=True)

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(fused)

    review_rows = [r for r in fused if r.get("review_status") == "fusion_conflict_review"]
    with review_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(review_rows)

    status_counts: dict = {}
    for r in fused:
        s = r.get("review_status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "whole_image_rows": len(wi_rows),
        "region_rows_total": sum(len(v) for v in region_rows_by_image.values()),
        "fused_rows": len(fused),
        "conflict_rows": len(review_rows),
        "review_status_counts": status_counts,
        "output_csv": str(output_csv),
        "review_csv": str(review_csv),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fuse whole-image and region OCR parsed events")
    parser.add_argument(
        "--whole-image-csv",
        default="data/_manifests/fr24_audit/fr24_ocr_parsed_events_probe_50.csv",
    )
    parser.add_argument(
        "--region-csv",
        default="data/_manifests/fr24_audit/fr24_region_parsed_events.csv",
    )
    parser.add_argument(
        "--output-csv",
        default="data/_manifests/fr24_audit/fr24_fused_event_candidates.csv",
    )
    parser.add_argument(
        "--review-csv",
        default="data/_manifests/fr24_audit/fr24_fused_review_queue.csv",
    )
    args = parser.parse_args()
    summary = run_fusion(
        Path(args.whole_image_csv),
        Path(args.region_csv),
        Path(args.output_csv),
        Path(args.review_csv),
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
