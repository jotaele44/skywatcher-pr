"""
FR24 SPIDERWEB INTAKE ADAPTER

Maps FR24 OCR selected candidate records (fr24_event_candidates_export.jsonl)
to the Spiderweb flight_event schema so dashboard-accepted candidates can flow
into the main Spiderweb intake pipeline.

Gate policy
-----------
Only records with selection_status == "selected_candidate" OR
dashboard_status == "dashboard_review_accepted_after_manual_review" are
mapped to flight_event records and written to the intake JSONL.  All other
records are written to a hold queue for later review.  No record is
auto-confirmed; every intake record carries confirmation_status=not_confirmed
and intake_status=candidate_intake_ready.

Outputs
-------
  fr24_spiderweb_intake_candidates.jsonl   flight_event-compatible records
  fr24_spiderweb_hold_queue.jsonl          Records held pending review
  fr24_spiderweb_adapter_summary.json      Counts + policy assertion
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

ADAPTER_VERSION = "fr24_spiderweb_adapter_v0.1.0"

# Records whose selection_status is in this set pass the gate unconditionally.
PASSTHROUGH_SELECTION_STATUSES = {"selected_candidate"}

# Records whose dashboard_status is in this set also pass the gate (they have
# been reviewed by a human and accepted).
PASSTHROUGH_DASHBOARD_STATUSES = {"dashboard_review_accepted_after_manual_review"}

# These labels must never appear in any output value field.
PROHIBITED_LABELS = {
    "confirmed",
    "confirmed_aircraft_event",
    "confirmed_anomaly",
    "confirmed_route",
    "verified_event",
    "validated_aircraft_event",
}

# Fields from the flight_event schema that the adapter tries to populate.
FLIGHT_EVENT_FIELDS = (
    "flight_id",
    "callsign",
    "aircraft_type",
    "operator",
    "origin_airport",
    "destination_airport",
    "max_altitude_ft",
    "avg_speed_mph",
    "takeoff_time",
    "num_screenshots",
)

# Adapter-added provenance fields appended to each intake record.
PROVENANCE_FIELDS = (
    "confirmation_status",
    "intake_status",
    "source_adapter",
    "source_candidate_id",
    "source_image_path",
    "source_image_name",
    "review_status",
    "selection_status",
    "dedup_status",
    "selected_field_disagreements",
    "missing_selected_fields",
    "conflict_count",
    "export_version",
    "fusion_version",
    "field_select_version",
    "dedup_version",
    "parser_version",
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _as_int(value: object) -> Optional[int]:
    try:
        v = int(str(value).strip())
        return v if v >= 0 else None
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> Optional[float]:
    try:
        v = float(str(value).strip())
        return v if v >= 0 else None
    except (TypeError, ValueError):
        return None


def _make_takeoff_time(row: dict) -> Optional[str]:
    """Combine playback_date + playback_time + playback_timezone into ISO-8601."""
    date = (row.get("playback_date") or "").strip()
    time = (row.get("playback_time") or "").strip()
    tz = (row.get("playback_timezone") or "").strip()
    if not date:
        return None
    ts = date
    if time:
        ts = f"{date}T{time}"
    if tz:
        ts = f"{ts}{tz}"
    return ts


def _flight_id(row: dict) -> str:
    cid = (row.get("candidate_id") or "").strip()
    if cid:
        return cid
    name = (row.get("image_name") or "").strip()
    return f"fr24::{name}" if name else f"fr24::unknown"


def is_intake_eligible(row: dict) -> bool:
    sel = (row.get("selection_status") or "").strip()
    dash = (row.get("dashboard_status") or "").strip()
    return sel in PASSTHROUGH_SELECTION_STATUSES or dash in PASSTHROUGH_DASHBOARD_STATUSES


def map_to_flight_event(row: dict) -> dict:
    """Map one export record to a flight_event-compatible dict."""
    out: dict = {}

    # ── Required flight_event fields ─────────────────────────────────────────
    out["flight_id"] = _flight_id(row)
    out["callsign"] = (row.get("callsign_or_label") or "").strip()

    # ── Optional flight_event fields ─────────────────────────────────────────
    out["aircraft_type"] = (row.get("aircraft_type") or None)
    out["operator"] = (row.get("operator") or None)
    out["origin_airport"] = (row.get("origin_code") or None)
    out["destination_airport"] = (row.get("destination_code") or None)
    out["max_altitude_ft"] = _as_int(row.get("barometric_altitude_ft"))
    out["avg_speed_mph"] = _as_float(row.get("ground_speed_mph"))
    out["takeoff_time"] = _make_takeoff_time(row)
    out["num_screenshots"] = 1

    # ── Provenance ────────────────────────────────────────────────────────────
    out["confirmation_status"] = "not_confirmed"
    out["intake_status"] = "candidate_intake_ready"
    out["source_adapter"] = ADAPTER_VERSION
    out["source_candidate_id"] = (row.get("candidate_id") or "").strip()
    out["source_image_path"] = (row.get("image_path") or "").strip()
    out["source_image_name"] = (row.get("image_name") or "").strip()
    out["review_status"] = (row.get("review_status") or "").strip()
    out["selection_status"] = (row.get("selection_status") or "").strip()
    out["dedup_status"] = (row.get("dedup_status") or "").strip()
    out["selected_field_disagreements"] = (row.get("selected_field_disagreements") or "").strip()
    out["missing_selected_fields"] = (row.get("missing_selected_fields") or "").strip()
    out["conflict_count"] = _as_int(row.get("conflict_count")) or 0
    out["export_version"] = (row.get("export_version") or "").strip()
    out["fusion_version"] = (row.get("fusion_version") or "").strip()
    out["field_select_version"] = (row.get("field_select_version") or "").strip()
    out["dedup_version"] = (row.get("dedup_version") or "").strip()
    out["parser_version"] = (row.get("parser_version") or "").strip()

    return out


def _has_prohibited_label(record: dict) -> bool:
    for value in record.values():
        if str(value) in PROHIBITED_LABELS:
            return True
    return False


def _validate_flight_event(record: dict) -> Optional[str]:
    """Return an error message if required fields are missing, else None."""
    if not record.get("flight_id"):
        return "missing flight_id"
    if record.get("callsign") == "" or record.get("callsign") is None:
        return "empty callsign"
    return None


# ── main pipeline ─────────────────────────────────────────────────────────────

def read_jsonl(path: Path) -> List[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def write_jsonl(path: Path, records: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def run(
    export_jsonl: Path,
    output_jsonl: Path,
    hold_jsonl: Path,
    summary_json: Path,
) -> dict:
    records = read_jsonl(export_jsonl)

    intake: List[dict] = []
    hold: List[dict] = []
    prohibited_dropped = 0
    validation_errors: List[str] = []

    for row in records:
        if _has_prohibited_label(row):
            prohibited_dropped += 1
            continue

        if is_intake_eligible(row):
            mapped = map_to_flight_event(row)
            err = _validate_flight_event(mapped)
            if err:
                validation_errors.append(
                    f"{row.get('candidate_id', '?')}: {err}"
                )
            if _has_prohibited_label(mapped):
                prohibited_dropped += 1
                continue
            intake.append(mapped)
        else:
            hold_row = dict(row)
            hold_row["hold_reason"] = "selection_status_not_passthrough"
            hold_row["adapter_version"] = ADAPTER_VERSION
            hold_row["confirmation_status"] = "not_confirmed"
            hold.append(hold_row)

    write_jsonl(output_jsonl, intake)
    write_jsonl(hold_jsonl, hold)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "export_jsonl": str(export_jsonl),
        "output_jsonl": str(output_jsonl),
        "hold_jsonl": str(hold_jsonl),
        "total_input_records": len(records),
        "intake_records": len(intake),
        "hold_records": len(hold),
        "prohibited_label_dropped": prohibited_dropped,
        "validation_errors": validation_errors,
        "selection_status_counts": dict(Counter(
            r.get("selection_status", "") for r in records
        )),
        "intake_status_counts": dict(Counter(
            r.get("intake_status", "") for r in intake
        )),
        "adapter_version": ADAPTER_VERSION,
        "policy": "candidate_only_no_auto_confirmation",
    }
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Map FR24 OCR selected candidates to Spiderweb flight_event intake format"
    )
    parser.add_argument(
        "--export-jsonl",
        default="data/_manifests/fr24_audit/fr24_event_candidates_export.jsonl",
    )
    parser.add_argument(
        "--output-jsonl",
        default="data/_manifests/fr24_audit/fr24_spiderweb_intake_candidates.jsonl",
    )
    parser.add_argument(
        "--hold-jsonl",
        default="data/_manifests/fr24_audit/fr24_spiderweb_hold_queue.jsonl",
    )
    parser.add_argument(
        "--summary-json",
        default="data/_manifests/fr24_audit/fr24_spiderweb_adapter_summary.json",
    )
    args = parser.parse_args()
    summary = run(
        Path(args.export_jsonl),
        Path(args.output_jsonl),
        Path(args.hold_jsonl),
        Path(args.summary_json),
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
