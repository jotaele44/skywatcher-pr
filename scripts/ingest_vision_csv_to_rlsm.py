#!/usr/bin/env python3
"""Fold the Claude-vision CSV lane into the RLSM store (strategy #2).

scripts/fr24_vision_ingest.py writes its 12 extracted fields to a standalone
CSV (outputs/fr24_selected_export.csv) that nothing downstream of the RLSM
sqlite ever sees. This ingester retires that disconnect: each CSV row becomes

  - an ocr_observations row (engine='claude_vision', zone='vision_full_frame',
    raw_text = the extraction JSON, raw_lines_json = the full CSV row) so the
    vision pass sits beside Tesseract as a queryable second opinion; and
  - an aircraft_observations row (source_zone='vision_full_frame') when the
    extraction carries a registration or callsign, so identity joins (FAA
    registry, waves, manual-log links) see vision-recovered aircraft too.

Rows are matched to screenshots by filename (the CSV stores the operator-Mac
absolute image path; the RLSM store indexes basenames), disambiguated by the
CSV's month_dir against rel_path when a basename repeats. Idempotent: a
screenshot that already has a claude_vision/vision_full_frame observation is
skipped, so re-runs and appended CSVs are safe.

Usage (operator, where the RLSM DB exists):
    python3 scripts/ingest_vision_csv_to_rlsm.py \
        --csv outputs/fr24_selected_export.csv \
        --rlsm-db data/rlsm/rlsm_screenshot_analysis.sqlite
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CSV = REPO / "outputs" / "fr24_selected_export.csv"
DEFAULT_DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"

ENGINE = "claude_vision"
ZONE = "vision_full_frame"

# The vision-extraction payload columns (CSV_FIELDNAMES minus the event/id
# plumbing); preserved verbatim as the observation's raw_text JSON.
EXTRACTION_FIELDS = [
    "callsign", "aircraft_type", "operator", "registration",
    "origin_code", "destination_code", "altitude_ft", "ground_speed_mph",
    "flight_status",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _int_or_none(value) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def match_screenshot_id(image_path: str, month_dir: str,
                        by_filename: dict) -> Optional[int]:
    """Resolve a CSV row to a screenshot_id by basename, then month_dir."""
    name = Path(image_path or "").name
    if not name:
        return None
    candidates = by_filename.get(name, [])
    if len(candidates) == 1:
        return candidates[0][0]
    if month_dir:
        scoped = [sid for sid, rel in candidates if month_dir in Path(rel).parts]
        if len(scoped) == 1:
            return scoped[0]
    return None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Ingest the Claude-vision extraction CSV into the RLSM store."
    )
    ap.add_argument("--csv", default=str(DEFAULT_CSV),
                    help="Vision CSV from scripts/fr24_vision_ingest.py")
    ap.add_argument("--rlsm-db", default=str(DEFAULT_DB), help="RLSM sqlite")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would be inserted without writing")
    args = ap.parse_args(argv)

    csv_path = Path(args.csv)
    db_path = Path(args.rlsm_db)
    if not csv_path.exists():
        print(f"FAIL — vision CSV not found: {csv_path}")
        return 1
    if not db_path.exists():
        print(f"FAIL — RLSM DB not found: {db_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    by_filename = defaultdict(list)
    for sid, filename, rel_path in conn.execute(
        "SELECT screenshot_id, filename, rel_path FROM screenshots"
    ):
        by_filename[filename].append((sid, rel_path))
    already = {
        sid for (sid,) in conn.execute(
            "SELECT DISTINCT screenshot_id FROM ocr_observations"
            " WHERE engine = ? AND zone = ?", (ENGINE, ZONE),
        )
    }

    now = _utc_now()
    run_id = None
    if not args.dry_run:
        cur = conn.execute(
            "INSERT INTO processing_runs (run_kind, started_at, status)"
            " VALUES ('vision_csv_ingest', ?, 'in_progress')", (now,),
        )
        run_id = cur.lastrowid

    stats = {
        "csv_rows": 0,
        "ocr_rows_inserted": 0,
        "aircraft_rows_inserted": 0,
        "skipped_already_ingested": 0,
        "skipped_unmatched_image": 0,
    }
    with csv_path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            stats["csv_rows"] += 1
            sid = match_screenshot_id(
                row.get("image_path", ""), row.get("month_dir", ""), by_filename
            )
            if sid is None:
                stats["skipped_unmatched_image"] += 1
                continue
            if sid in already:
                stats["skipped_already_ingested"] += 1
                continue
            already.add(sid)
            extraction = {k: (row.get(k) or "") for k in EXTRACTION_FIELDS}
            stats["ocr_rows_inserted"] += 1
            if not args.dry_run:
                conn.execute(
                    "INSERT INTO ocr_observations (screenshot_id, run_id, zone,"
                    " raw_text, raw_lines_json, engine, ocr_status, observed_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, 'ok', ?)",
                    (sid, run_id, ZONE, json.dumps(extraction, sort_keys=True),
                     json.dumps(row, sort_keys=True), ENGINE, now),
                )
            registration = (row.get("registration") or "").strip().upper()
            callsign = (row.get("callsign") or "").strip()
            if registration or callsign:
                stats["aircraft_rows_inserted"] += 1
                if not args.dry_run:
                    # OR IGNORE: the ix_air_dedup partial unique index protects
                    # (screenshot_id, registration, source_zone).
                    conn.execute(
                        "INSERT OR IGNORE INTO aircraft_observations"
                        " (screenshot_id, run_id, registration, callsign,"
                        " aircraft_type, altitude_ft, operator_text,"
                        " identity_status, source_zone, raw_excerpt, observed_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, 'recovered', ?, ?, ?)",
                        (sid, run_id, registration or None, callsign or None,
                         (row.get("aircraft_type") or "").strip() or None,
                         _int_or_none(row.get("altitude_ft")),
                         (row.get("operator") or "").strip() or None,
                         ZONE, json.dumps(extraction, sort_keys=True), now),
                    )

    if not args.dry_run:
        conn.execute(
            "UPDATE processing_runs SET ended_at = ?, status = 'completed',"
            " n_inputs = ?, n_processed = ?, n_failed = ? WHERE run_id = ?",
            (_utc_now(), stats["csv_rows"], stats["ocr_rows_inserted"],
             stats["skipped_unmatched_image"], run_id),
        )
        conn.commit()
    conn.close()
    print(json.dumps({"dry_run": bool(args.dry_run), **stats}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
