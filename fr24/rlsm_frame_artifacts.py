"""Persist screenshot frame, map-state, and GUI-artifact observations.

The classifier is deliberately conservative. It records provider/layout evidence
from OCR and image dimensions, but never invents geographic coordinates, zoom,
or bearing. Unknown and failed frames remain explicit reviewable observations.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"

METHOD = "ocr_layout_markers_v1"

FR24_MARKERS = (
    "flightradar",
    "barometric",
    "ground speed",
    "3d view",
    "more info",
    "departed",
    "arriving",
    "arrived",
    "altitude",
    "reg.",
    "route",
    "follow",
)
EARTH_MARKERS = (
    "google earth",
    "google maps",
    "street view",
    "layers",
    "search here",
    "map data",
)
SELECTED_FLIGHT_MARKERS = (
    "altitude",
    "ground speed",
    "barometric",
    "reg.",
    "callsign",
    "route",
)
REGISTRATION_RE = re.compile(r"\bN[0-9]{1,5}[A-Z]{0,2}\b", re.I)

GUI_ZONE_TYPES = {
    "status_bar": "device_status_bar",
    "top_bar": "top_navigation",
    "aircraft_card": "aircraft_information_panel",
    "side_panel": "side_information_panel",
    "bottom_panel": "bottom_information_panel",
    "bottom_actions": "bottom_action_controls",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS frame_observations (
    frame_obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    run_id INTEGER REFERENCES processing_runs(run_id),
    frame_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    orientation TEXT NOT NULL,
    confidence REAL NOT NULL,
    classification_method TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'unreviewed',
    observed_at TEXT NOT NULL,
    UNIQUE(screenshot_id, classification_method)
);
CREATE INDEX IF NOT EXISTS ix_frame_screenshot
    ON frame_observations(screenshot_id);
CREATE INDEX IF NOT EXISTS ix_frame_type
    ON frame_observations(frame_type);

CREATE TABLE IF NOT EXISTS map_state_observations (
    map_state_id INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    frame_obs_id INTEGER NOT NULL REFERENCES frame_observations(frame_obs_id),
    viewport_x INTEGER NOT NULL,
    viewport_y INTEGER NOT NULL,
    viewport_w INTEGER NOT NULL,
    viewport_h INTEGER NOT NULL,
    center_lat REAL,
    center_lon REAL,
    zoom REAL,
    bearing_deg REAL,
    extent_geojson TEXT,
    geolocation_status TEXT NOT NULL,
    confidence REAL NOT NULL,
    method TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    UNIQUE(screenshot_id, method)
);
CREATE INDEX IF NOT EXISTS ix_map_state_screenshot
    ON map_state_observations(screenshot_id);

CREATE TABLE IF NOT EXISTS gui_artifact_observations (
    gui_artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    frame_obs_id INTEGER NOT NULL REFERENCES frame_observations(frame_obs_id),
    source_obs_id INTEGER REFERENCES ocr_observations(obs_id),
    artifact_type TEXT NOT NULL,
    bbox_x INTEGER,
    bbox_y INTEGER,
    bbox_w INTEGER,
    bbox_h INTEGER,
    raw_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    confidence REAL,
    extraction_status TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'unreviewed',
    method TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    UNIQUE(screenshot_id, source_obs_id, artifact_type, method)
);
CREATE INDEX IF NOT EXISTS ix_gui_screenshot
    ON gui_artifact_observations(screenshot_id);
CREATE INDEX IF NOT EXISTS ix_gui_type
    ON gui_artifact_observations(artifact_type);
"""


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def normalize_text(text: str) -> str:
    return " ".join((text or "").split())


def classify_frame(observations: list[dict[str, Any]]) -> dict[str, Any]:
    by_zone = {str(row["zone"]): row for row in observations}
    combined = "\n".join(
        str(row.get("raw_text") or "")
        for row in observations
        if row.get("ocr_status") in {"ok", "empty"}
    )
    low = combined.casefold()
    fr24_hits = sorted(marker for marker in FR24_MARKERS if marker in low)
    earth_hits = sorted(marker for marker in EARTH_MARKERS if marker in low)
    card_text = str(by_zone.get("aircraft_card", {}).get("raw_text") or "")
    selected_hits = sorted(
        marker for marker in SELECTED_FLIGHT_MARKERS if marker in card_text.casefold()
    )
    has_registration = bool(REGISTRATION_RE.search(card_text))
    failed_zones = sorted(
        str(row["zone"])
        for row in observations
        if row.get("ocr_status") == "failed"
    )

    if len(fr24_hits) >= 2 and (selected_hits or has_registration):
        frame_type = "fr24_selected_flight"
        provider = "flightradar24"
        confidence = 0.9 if has_registration else 0.82
    elif len(fr24_hits) >= 2:
        frame_type = "fr24_map"
        provider = "flightradar24"
        confidence = 0.75
    elif earth_hits:
        frame_type = "earth_or_maps"
        provider = "google"
        confidence = min(0.85, 0.55 + 0.1 * len(earth_hits))
    elif combined.strip():
        frame_type = "map_or_other"
        provider = "unknown"
        confidence = 0.35
    else:
        frame_type = "unknown"
        provider = "unknown"
        confidence = 0.1

    return {
        "frame_type": frame_type,
        "provider": provider,
        "confidence": round(confidence, 3),
        "review_status": "needs_review" if frame_type in {"unknown", "map_or_other"} else "unreviewed",
        "evidence": {
            "fr24_markers": fr24_hits,
            "earth_markers": earth_hits,
            "selected_flight_markers": selected_hits,
            "registration_visible": has_registration,
            "failed_zones": failed_zones,
            "zones_present": sorted(by_zone),
        },
    }


def map_viewport(width: int | None, height: int | None) -> tuple[int, int, int, int]:
    width = max(0, int(width or 0))
    height = max(0, int(height or 0))
    if height >= width:
        return (0, int(height * 0.05), width, int(height * 0.60))
    return (0, int(height * 0.08), int(width * 0.70), int(height * 0.87))


def _latest_observations(conn: sqlite3.Connection, sid: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT obs_id, zone, bbox_x, bbox_y, bbox_w, bbox_h, raw_text,
                  confidence_mean, ocr_status, ocr_error
           FROM ocr_observations
           WHERE obs_id IN (
               SELECT MAX(obs_id)
               FROM ocr_observations
               WHERE screenshot_id=?
               GROUP BY zone
           )
           ORDER BY zone""",
        (sid,),
    ).fetchall()
    fields = (
        "obs_id",
        "zone",
        "bbox_x",
        "bbox_y",
        "bbox_w",
        "bbox_h",
        "raw_text",
        "confidence_mean",
        "ocr_status",
        "ocr_error",
    )
    return [dict(zip(fields, row, strict=True)) for row in rows]


def _insert_gui_artifacts(
    conn: sqlite3.Connection,
    sid: int,
    frame_obs_id: int,
    observations: list[dict[str, Any]],
    observed_at: str,
) -> int:
    count = 0
    for row in observations:
        artifact_type = GUI_ZONE_TYPES.get(str(row["zone"]))
        if artifact_type is None:
            continue
        raw_text = str(row.get("raw_text") or "")
        status = str(row.get("ocr_status") or "failed")
        review = "needs_review" if status == "failed" else "unreviewed"
        conn.execute(
            """INSERT OR REPLACE INTO gui_artifact_observations
               (screenshot_id, frame_obs_id, source_obs_id, artifact_type,
                bbox_x, bbox_y, bbox_w, bbox_h, raw_text, normalized_text,
                confidence, extraction_status, review_status, method, observed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sid,
                frame_obs_id,
                row["obs_id"],
                artifact_type,
                row["bbox_x"],
                row["bbox_y"],
                row["bbox_w"],
                row["bbox_h"],
                raw_text,
                normalize_text(raw_text),
                row["confidence_mean"],
                status,
                review,
                METHOD,
                observed_at,
            ),
        )
        count += 1
    return count


def run(db_path: Path = DB, limit: int = 0) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"RLSM DB not found: {db_path}")
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    ensure_schema(conn)

    sql = """SELECT screenshot_id, width, height
             FROM screenshots
             WHERE ingest_status='ok'
             ORDER BY screenshot_id"""
    if limit:
        sql += f" LIMIT {int(limit)}"
    screenshots = conn.execute(sql).fetchall()
    cursor = conn.execute(
        """INSERT INTO processing_runs
           (run_kind, started_at, status, n_inputs, n_processed, n_failed, notes)
           VALUES ('frame_gui_artifacts', ?, 'in_progress', ?, 0, 0, ?)""",
        (_iso_now(), len(screenshots), json.dumps({"method": METHOD})),
    )
    run_id = int(cursor.lastrowid)
    conn.commit()

    frame_counts: dict[str, int] = {}
    gui_count = 0
    failed = 0
    for sid, width, height in screenshots:
        try:
            observations = _latest_observations(conn, int(sid))
            result = classify_frame(observations)
            orientation = "portrait" if int(height or 0) >= int(width or 0) else "landscape"
            observed_at = _iso_now()
            with conn:
                conn.execute(
                    "DELETE FROM map_state_observations WHERE screenshot_id=? AND method=?",
                    (sid, METHOD),
                )
                conn.execute(
                    "DELETE FROM gui_artifact_observations WHERE screenshot_id=? AND method=?",
                    (sid, METHOD),
                )
                conn.execute(
                    "DELETE FROM frame_observations WHERE screenshot_id=? AND classification_method=?",
                    (sid, METHOD),
                )
                frame_cursor = conn.execute(
                    """INSERT INTO frame_observations
                       (screenshot_id, run_id, frame_type, provider, orientation,
                        confidence, classification_method, evidence_json,
                        review_status, observed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sid,
                        run_id,
                        result["frame_type"],
                        result["provider"],
                        orientation,
                        result["confidence"],
                        METHOD,
                        json.dumps(result["evidence"], sort_keys=True),
                        result["review_status"],
                        observed_at,
                    ),
                )
                frame_obs_id = int(frame_cursor.lastrowid)
                vx, vy, vw, vh = map_viewport(width, height)
                conn.execute(
                    """INSERT INTO map_state_observations
                       (screenshot_id, frame_obs_id, viewport_x, viewport_y,
                        viewport_w, viewport_h, center_lat, center_lon, zoom,
                        bearing_deg, extent_geojson, geolocation_status,
                        confidence, method, observed_at)
                       VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL,
                               'unsupported', ?, ?, ?)""",
                    (
                        sid,
                        frame_obs_id,
                        vx,
                        vy,
                        vw,
                        vh,
                        min(0.5, result["confidence"]),
                        METHOD,
                        observed_at,
                    ),
                )
                gui_count += _insert_gui_artifacts(
                    conn,
                    int(sid),
                    frame_obs_id,
                    observations,
                    observed_at,
                )
            frame_counts[result["frame_type"]] = frame_counts.get(result["frame_type"], 0) + 1
        except (sqlite3.DatabaseError, ValueError, TypeError) as exc:
            failed += 1
            print(f"[frame-artifacts] screenshot_id={sid} failed: {exc}", flush=True)

    status = "completed" if failed == 0 else "failed"
    conn.execute(
        """UPDATE processing_runs
           SET ended_at=?, status=?, n_processed=?, n_failed=?, notes=?
           WHERE run_id=?""",
        (
            _iso_now(),
            status,
            len(screenshots) - failed,
            failed,
            json.dumps(
                {"method": METHOD, "frame_types": frame_counts, "gui_artifacts": gui_count},
                sort_keys=True,
            ),
            run_id,
        ),
    )
    conn.commit()
    conn.close()
    return {
        "run_id": run_id,
        "targets": len(screenshots),
        "processed": len(screenshots) - failed,
        "failed": failed,
        "frame_types": frame_counts,
        "gui_artifacts": gui_count,
        "status": status,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        result = run(args.db, args.limit)
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
