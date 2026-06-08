"""
FR24 SELECTED CANDIDATES EXPORT

Packages selected FR24 OCR candidate rows into CSV, JSONL, and source-manifest
artifacts for downstream Spiderweb consumers. This layer is the export channel
for review-gated candidate records. It does not confirm events.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import List

EXPORT_VERSION = "fr24_selected_export_v0.1.0"

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

PROHIBITED_LABELS = {
    "confirmed",
    "confirmed_aircraft_event",
    "confirmed_anomaly",
    "confirmed_route",
    "verified_event",
    "validated_aircraft_event",
}

PROVENANCE_VERSION_FIELDS = (
    "fusion_version",
    "field_select_version",
    "dedup_version",
    "parser_version",
)


def read_csv(path: Path) -> List[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return list(csv.DictReader(path.open(encoding="utf-8")))


def write_csv(path: Path, rows: List[dict], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def write_jsonl(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def has_prohibited_label(row: dict) -> bool:
    for key in ("confirmation_status", "dedup_status", "selection_status", "review_status"):
        value = (row.get(key) or "").strip().lower()
        if value in PROHIBITED_LABELS:
            return True
    return False


def build_ledger_index(ledger_csv: Path) -> dict[str, dict]:
    """Map image_path → best ledger record for batch traceability.

    Prefers whole-image rows over region rows. Within a mode, prefers complete
    over failed, and the latest finished_at wins ties.
    """
    rows = read_csv(ledger_csv)
    index: dict[str, dict] = {}
    for row in rows:
        image_path = (row.get("image_path") or "").strip()
        if not image_path:
            continue
        existing = index.get(image_path)
        if existing is None:
            index[image_path] = row
            continue
        existing_score = _ledger_score(existing)
        new_score = _ledger_score(row)
        if new_score > existing_score:
            index[image_path] = row
    return index


def _ledger_score(row: dict) -> tuple:
    mode_rank = 1 if row.get("mode") == "whole-image" else 0
    status_rank = 1 if row.get("status") == "complete" else 0
    finished = row.get("finished_at", "") or ""
    return (mode_rank, status_rank, finished)


def enrich_row(row: dict, source_csv: Path, ledger_index: dict[str, dict]) -> dict:
    out = dict(row)
    out["confirmation_status"] = "not_confirmed"
    out["source_csv_path"] = str(source_csv)
    out["export_version"] = EXPORT_VERSION
    ledger_row = ledger_index.get((row.get("image_path") or "").strip(), {})
    out["source_batch_id"] = ledger_row.get("batch_id", "")
    out["source_batch_finished_at"] = ledger_row.get("finished_at", "")
    return out


def export_fieldnames() -> List[str]:
    base = ["candidate_id", "image_path", "image_name"]
    field_columns: List[str] = []
    for field in SELECT_FIELDS:
        field_columns.append(field)
        field_columns.append(f"{field}_selected_source")
    tail = [
        "review_status",
        "selection_status",
        "dedup_status",
        "confirmation_status",
        "selected_field_disagreements",
        "missing_selected_fields",
        "conflict_count",
        "whole_confidence",
        "region_confidence",
        "source_csv_path",
        "source_batch_id",
        "source_batch_finished_at",
        "export_version",
        "fusion_version",
        "field_select_version",
        "dedup_version",
        "parser_version",
    ]
    return base + field_columns + tail


def write_source_manifest(
    path: Path,
    inputs: dict[str, int],
    outputs: dict[str, int],
    upstream_versions: dict[str, List[str]],
) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "export_version": EXPORT_VERSION,
        "inputs": [{"path": p, "row_count": c} for p, c in inputs.items()],
        "outputs": [{"path": p, "row_count": c} for p, c in outputs.items()],
        "upstream_versions": {k: sorted(set(v)) for k, v in upstream_versions.items()},
        "policy": "candidate_only_no_auto_confirmation",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run(
    selected_csv: Path,
    field_review_csv: Path,
    duplicate_review_csv: Path,
    ledger_csv: Path,
    output_csv: Path,
    output_jsonl: Path,
    summary_json: Path,
    source_manifest_json: Path,
) -> dict:
    selected_rows = read_csv(selected_csv)
    field_review_rows = read_csv(field_review_csv)
    duplicate_review_rows = read_csv(duplicate_review_csv)
    ledger_rows = read_csv(ledger_csv)
    ledger_index = build_ledger_index(ledger_csv)

    enriched: List[dict] = []
    dropped = 0
    for row in selected_rows:
        if has_prohibited_label(row):
            dropped += 1
            continue
        enriched.append(enrich_row(row, selected_csv, ledger_index))

    fieldnames = export_fieldnames()
    write_csv(output_csv, enriched, fieldnames)
    write_jsonl(output_jsonl, enriched)

    upstream_versions: dict[str, List[str]] = {k: [] for k in PROVENANCE_VERSION_FIELDS}
    for row in enriched:
        for key in PROVENANCE_VERSION_FIELDS:
            value = (row.get(key) or "").strip()
            if value:
                upstream_versions[key].append(value)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selected_csv": str(selected_csv),
        "field_review_csv": str(field_review_csv),
        "duplicate_review_csv": str(duplicate_review_csv),
        "ledger_csv": str(ledger_csv),
        "output_csv": str(output_csv),
        "output_jsonl": str(output_jsonl),
        "source_manifest_json": str(source_manifest_json),
        "input_rows": len(selected_rows),
        "field_review_rows": len(field_review_rows),
        "duplicate_review_rows": len(duplicate_review_rows),
        "ledger_rows": len(ledger_rows),
        "exported_rows": len(enriched),
        "prohibited_label_dropped": dropped,
        "selection_status_counts": dict(Counter(r.get("selection_status", "") for r in enriched)),
        "review_status_counts": dict(Counter(r.get("review_status", "") for r in enriched)),
        "dedup_status_counts": dict(Counter(r.get("dedup_status", "") for r in enriched)),
        "export_version": EXPORT_VERSION,
        "policy": "candidate_only_no_auto_confirmation",
    }
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    write_source_manifest(
        source_manifest_json,
        inputs={
            str(selected_csv): len(selected_rows),
            str(field_review_csv): len(field_review_rows),
            str(duplicate_review_csv): len(duplicate_review_rows),
            str(ledger_csv): len(ledger_rows),
        },
        outputs={
            str(output_csv): len(enriched),
            str(output_jsonl): len(enriched),
            str(summary_json): 1,
        },
        upstream_versions=upstream_versions,
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Export FR24 selected OCR candidate rows")
    parser.add_argument("--selected-csv", default="data/_manifests/fr24_audit/fr24_event_candidates_selected.csv")
    parser.add_argument("--field-review-csv", default="data/_manifests/fr24_audit/fr24_field_selection_review_queue.csv")
    parser.add_argument("--duplicate-review-csv", default="data/_manifests/fr24_audit/fr24_fused_duplicate_review_queue.csv")
    parser.add_argument("--ledger-csv", default="data/_manifests/fr24_audit/fr24_batch_run_ledger.csv")
    parser.add_argument("--output-csv", default="data/_manifests/fr24_audit/fr24_event_candidates_export.csv")
    parser.add_argument("--output-jsonl", default="data/_manifests/fr24_audit/fr24_event_candidates_export.jsonl")
    parser.add_argument("--summary-json", default="data/_manifests/fr24_audit/fr24_export_summary.json")
    parser.add_argument("--source-manifest-json", default="data/_manifests/fr24_audit/fr24_source_manifest_extension.json")
    args = parser.parse_args()
    summary = run(
        Path(args.selected_csv),
        Path(args.field_review_csv),
        Path(args.duplicate_review_csv),
        Path(args.ledger_csv),
        Path(args.output_csv),
        Path(args.output_jsonl),
        Path(args.summary_json),
        Path(args.source_manifest_json),
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
