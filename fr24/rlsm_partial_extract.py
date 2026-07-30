"""Extract structured aircraft and labels from partially successful OCR frames."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _start_run(conn: sqlite3.Connection, kind: str, targets: int) -> int:
    cursor = conn.execute(
        """INSERT INTO processing_runs
           (run_kind, started_at, status, n_inputs, n_processed, n_failed, notes)
           VALUES (?, ?, 'in_progress', ?, 0, 0, ?)""",
        (f"partial_{kind}", _iso_now(), targets, json.dumps({"ocr_status": "partial"})),
    )
    conn.commit()
    return int(cursor.lastrowid)


def _finish_run(
    conn: sqlite3.Connection, run_id: int, processed: int, failed: int, notes: dict[str, Any]
) -> None:
    conn.execute(
        """UPDATE processing_runs SET ended_at=?, status=?, n_processed=?,
                  n_failed=?, notes=? WHERE run_id=?""",
        (
            _iso_now(),
            "completed" if failed == 0 else "failed",
            processed,
            failed,
            json.dumps(notes, sort_keys=True),
            run_id,
        ),
    )
    conn.commit()


def extract_aircraft(conn: sqlite3.Connection, limit: int = 0) -> dict[str, int]:
    from fr24.rlsm_extractors import _latest_zone_observations, _scan_text

    sql = """SELECT s.screenshot_id FROM screenshots s
             WHERE s.ocr_status='partial'
               AND NOT EXISTS (SELECT 1 FROM aircraft_observations a WHERE a.screenshot_id=s.screenshot_id)
             ORDER BY s.screenshot_id"""
    if limit:
        sql += f" LIMIT {int(limit)}"
    targets = [int(row[0]) for row in conn.execute(sql)]
    run_id = _start_run(conn, "aircraft_extract", len(targets))
    emitted = failed = 0
    for sid in targets:
        try:
            rows = [
                row
                for row in _latest_zone_observations(conn, sid)
                if row[0] in {"aircraft_card", "top_bar", "map_center", "label_layer"} and row[1]
            ]
            combined = " ".join(str(row[1]) for row in rows)
            if not combined:
                continue
            fields = _scan_text(combined)
            if not fields:
                continue
            confidences = [float(row[3]) for row in rows if row[3] is not None]
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
            registration, aircraft_type = fields.get("registration"), fields.get("aircraft_type")
            if registration and aircraft_type:
                identity_status, confidence = "confirmed", min(0.95, avg_conf / 100 + 0.1)
            elif registration:
                identity_status, confidence = "partial", min(0.75, avg_conf / 100)
            else:
                identity_status, confidence = "unknown", min(0.4, avg_conf / 100)
            conn.execute(
                """INSERT INTO aircraft_observations
                   (screenshot_id, run_id, registration, callsign, aircraft_type,
                    altitude_ft, speed_kt, heading_deg, operator_text,
                    identity_status, confidence, source_zone, raw_excerpt, observed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sid,
                    run_id,
                    registration,
                    fields.get("callsign"),
                    aircraft_type,
                    fields.get("altitude_ft"),
                    fields.get("speed_kt"),
                    fields.get("heading_deg"),
                    fields.get("operator_text"),
                    identity_status,
                    confidence,
                    "+".join(str(row[0]) for row in rows),
                    combined[:200],
                    _iso_now(),
                ),
            )
            conn.commit()
            emitted += 1
        except (sqlite3.DatabaseError, ValueError, TypeError):
            failed += 1
    _finish_run(conn, run_id, emitted, failed, {"targets": len(targets), "emitted": emitted})
    return {"targets": len(targets), "emitted": emitted, "failed": failed}


def extract_labels(conn: sqlite3.Connection, limit: int = 0) -> dict[str, int]:
    from fr24.rlsm_extractors import (
        LABEL_ZONE_WEIGHTS,
        _latest_zone_observations,
        _normalize_label,
        scan_words_for_pois,
    )
    from fr24.rlsm_wordboxes import load_words, union_box

    sql = """SELECT s.screenshot_id FROM screenshots s
             WHERE s.ocr_status='partial'
               AND NOT EXISTS (SELECT 1 FROM labeled_pins p WHERE p.screenshot_id=s.screenshot_id)
             ORDER BY s.screenshot_id"""
    if limit:
        sql += f" LIMIT {int(limit)}"
    targets = [int(row[0]) for row in conn.execute(sql)]
    run_id = _start_run(conn, "labeled_poi", len(targets))
    emitted = failed = skipped_no_boxes = 0
    for sid in targets:
        try:
            best: dict[str, dict[str, Any]] = {}
            saw_boxes = False
            for zone, _raw_text, raw_lines_json, _confidence in _latest_zone_observations(
                conn, sid
            ):
                weight = LABEL_ZONE_WEIGHTS.get(zone)
                if weight is None:
                    continue
                words = load_words(raw_lines_json)
                if not words:
                    continue
                saw_boxes = True
                for hit in scan_words_for_pois(words, zone_weight=weight):
                    key = str(hit["label"]).casefold()
                    if key not in best or hit["confidence"] > best[key]["confidence"]:
                        best[key] = hit
            if not saw_boxes:
                skipped_no_boxes += 1
                continue
            for hit in best.values():
                box = union_box(hit["words"])
                bx, by, bw, bh = box if box else (None, None, None, None)
                cx, cy = (bx + bw // 2, by + bh // 2) if box else (None, None)
                conn.execute(
                    """INSERT INTO labeled_pins
                       (screenshot_id, run_id, raw_label, normalized_label,
                        bbox_x, bbox_y, bbox_w, bbox_h, centroid_x, centroid_y,
                        pin_type_guess, confidence, review_status, observed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unreviewed', ?)""",
                    (
                        sid,
                        run_id,
                        hit["label"],
                        _normalize_label(hit["label"]),
                        bx,
                        by,
                        bw,
                        bh,
                        cx,
                        cy,
                        hit["pin_type"],
                        hit["confidence"],
                        _iso_now(),
                    ),
                )
                emitted += 1
            conn.commit()
        except (sqlite3.DatabaseError, ValueError, TypeError):
            failed += 1
    _finish_run(
        conn,
        run_id,
        len(targets) - failed,
        failed,
        {"targets": len(targets), "emitted": emitted, "skipped_no_word_boxes": skipped_no_boxes},
    )
    return {
        "targets": len(targets),
        "emitted": emitted,
        "failed": failed,
        "skipped_no_word_boxes": skipped_no_boxes,
    }


def run(db_path: Path = DB, limit: int = 0) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"RLSM DB not found: {db_path}")
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS ix_air_dedup
        ON aircraft_observations(screenshot_id, registration, source_zone)
        WHERE registration IS NOT NULL AND TRIM(registration) != ''""")
    conn.commit()
    result = {"aircraft": extract_aircraft(conn, limit), "labels": extract_labels(conn, limit)}
    conn.close()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        result = run(args.db, args.limit)
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    failures = result["aircraft"]["failed"] + result["labels"]["failed"]
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
