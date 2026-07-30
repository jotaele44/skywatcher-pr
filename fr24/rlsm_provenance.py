"""Backfill field-level provenance for screenshot-derived structured objects."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS extraction_field_provenance (
    provenance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    object_type TEXT NOT NULL,
    object_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    method TEXT NOT NULL,
    method_version TEXT NOT NULL,
    confidence REAL,
    validation_outcome TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    UNIQUE(object_type, object_id, field_name)
);
CREATE INDEX IF NOT EXISTS ix_field_prov_screenshot
    ON extraction_field_provenance(screenshot_id);
CREATE INDEX IF NOT EXISTS ix_field_prov_object
    ON extraction_field_provenance(object_type, object_id);
CREATE INDEX IF NOT EXISTS ix_field_prov_source
    ON extraction_field_provenance(source_type);
"""


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _insert_field(
    conn: sqlite3.Connection,
    *,
    screenshot_id: int,
    object_type: str,
    object_id: int,
    field_name: str,
    value: Any,
    source_type: str,
    source_ref: str,
    method: str,
    method_version: str,
    confidence: float | None,
    validation_outcome: str,
    observed_at: str,
) -> int:
    if value is None:
        return 0
    conn.execute(
        """INSERT INTO extraction_field_provenance
           (screenshot_id, object_type, object_id, field_name, value_json,
            source_type, source_ref, method, method_version, confidence,
            validation_outcome, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(object_type, object_id, field_name) DO UPDATE SET
               screenshot_id=excluded.screenshot_id,
               value_json=excluded.value_json,
               source_type=excluded.source_type,
               source_ref=excluded.source_ref,
               method=excluded.method,
               method_version=excluded.method_version,
               confidence=excluded.confidence,
               validation_outcome=excluded.validation_outcome,
               observed_at=excluded.observed_at""",
        (
            screenshot_id,
            object_type,
            object_id,
            field_name,
            _json(value),
            source_type,
            source_ref,
            method,
            method_version,
            confidence,
            validation_outcome,
            observed_at,
        ),
    )
    return 1


def _insert_fields(
    conn: sqlite3.Connection,
    *,
    screenshot_id: int,
    object_type: str,
    object_id: int,
    fields: Iterable[tuple[str, Any]],
    source_type: str,
    source_ref: str,
    method: str,
    method_version: str = "1",
    confidence: float | None = None,
    validation_outcome: str = "UNVERIFIED",
    observed_at: str,
) -> int:
    return sum(
        _insert_field(
            conn,
            screenshot_id=screenshot_id,
            object_type=object_type,
            object_id=object_id,
            field_name=name,
            value=value,
            source_type=source_type,
            source_ref=source_ref,
            method=method,
            method_version=method_version,
            confidence=confidence,
            validation_outcome=validation_outcome,
            observed_at=observed_at,
        )
        for name, value in fields
    )


def _latest_ocr_sources(conn: sqlite3.Connection) -> dict[int, dict[str, int]]:
    rows = conn.execute(
        """SELECT screenshot_id, zone, obs_id
           FROM ocr_observations
           WHERE obs_id IN (
               SELECT MAX(obs_id)
               FROM ocr_observations
               GROUP BY screenshot_id, zone
           )"""
    ).fetchall()
    result: dict[int, dict[str, int]] = {}
    for sid, zone, obs_id in rows:
        result.setdefault(int(sid), {})[str(zone)] = int(obs_id)
    return result


def _source_for(
    sources: dict[int, dict[str, int]],
    screenshot_id: int,
    preferred_zones: tuple[str, ...],
) -> str:
    by_zone = sources.get(screenshot_id, {})
    selected = [by_zone[zone] for zone in preferred_zones if zone in by_zone]
    if not selected:
        selected = sorted(by_zone.values())
    if not selected:
        return f"screenshot:{screenshot_id}"
    return ",".join(f"ocr_observations:{obs_id}" for obs_id in selected)


def _screenshot_shas(conn: sqlite3.Connection) -> dict[int, str]:
    return {
        int(sid): str(sha)
        for sid, sha in conn.execute("SELECT screenshot_id, sha256 FROM screenshots")
    }


def _labels(
    conn: sqlite3.Connection,
    sources: dict[int, dict[str, int]],
    observed_at: str,
) -> tuple[int, int]:
    objects = fields = 0
    rows = conn.execute(
        """SELECT pin_id, screenshot_id, raw_label, normalized_label,
                  bbox_x, bbox_y, bbox_w, bbox_h, centroid_x, centroid_y,
                  pin_type_guess, confidence, review_status
           FROM labeled_pins ORDER BY pin_id"""
    )
    for row in rows:
        pin_id, sid = int(row[0]), int(row[1])
        confidence = float(row[11]) if row[11] is not None else None
        outcome = "VALID" if confidence is not None and confidence >= 0.5 else "UNVERIFIED"
        fields += _insert_fields(
            conn,
            screenshot_id=sid,
            object_type="labeled_pin",
            object_id=pin_id,
            fields=zip(
                (
                    "raw_label",
                    "normalized_label",
                    "bbox_x",
                    "bbox_y",
                    "bbox_w",
                    "bbox_h",
                    "centroid_x",
                    "centroid_y",
                    "pin_type_guess",
                    "confidence",
                    "review_status",
                ),
                row[2:],
                strict=True,
            ),
            source_type="ocr_observation",
            source_ref=_source_for(
                sources,
                sid,
                ("label_layer", "map_center", "aircraft_card"),
            ),
            method="wordbox_gazetteer_match",
            confidence=confidence,
            validation_outcome=outcome,
            observed_at=observed_at,
        )
        objects += 1
    return objects, fields


def _aircraft(
    conn: sqlite3.Connection,
    sources: dict[int, dict[str, int]],
    observed_at: str,
) -> tuple[int, int]:
    objects = fields = 0
    rows = conn.execute(
        """SELECT aircraft_obs_id, screenshot_id, registration, callsign,
                  aircraft_type, altitude_ft, speed_kt, heading_deg,
                  operator_text, identity_status, confidence, source_zone,
                  raw_excerpt
           FROM aircraft_observations ORDER BY aircraft_obs_id"""
    )
    names = (
        "registration",
        "callsign",
        "aircraft_type",
        "altitude_ft",
        "speed_kt",
        "heading_deg",
        "operator_text",
        "identity_status",
        "confidence",
        "source_zone",
        "raw_excerpt",
    )
    for row in rows:
        object_id, sid = int(row[0]), int(row[1])
        identity = str(row[9] or "unknown")
        confidence = float(row[10]) if row[10] is not None else None
        if identity == "confirmed":
            outcome = "VALID"
        elif identity == "conflicting":
            outcome = "CONFLICTED"
        else:
            outcome = "UNVERIFIED"
        fields += _insert_fields(
            conn,
            screenshot_id=sid,
            object_type="aircraft_observation",
            object_id=object_id,
            fields=zip(names, row[2:], strict=True),
            source_type="ocr_observation",
            source_ref=_source_for(
                sources,
                sid,
                ("aircraft_card", "top_bar", "map_center"),
            ),
            method="aircraft_text_parser",
            confidence=confidence,
            validation_outcome=outcome,
            observed_at=observed_at,
        )
        objects += 1
    return objects, fields


def _tracks(
    conn: sqlite3.Connection,
    shas: dict[int, str],
    observed_at: str,
) -> tuple[int, int]:
    objects = fields = 0
    rows = conn.execute(
        """SELECT track_feat_id, screenshot_id, path_shape, has_loop,
                  has_orbit, has_hover, has_gap, follows_coast, near_airport,
                  track_length_px, bbox_x, bbox_y, bbox_w, bbox_h, confidence
           FROM flight_track_features ORDER BY track_feat_id"""
    )
    names = (
        "path_shape",
        "has_loop",
        "has_orbit",
        "has_hover",
        "has_gap",
        "follows_coast",
        "near_airport",
        "track_length_px",
        "bbox_x",
        "bbox_y",
        "bbox_w",
        "bbox_h",
        "confidence",
    )
    for row in rows:
        object_id, sid = int(row[0]), int(row[1])
        confidence = float(row[14]) if row[14] is not None else None
        pixel_derived = row[10] is not None and confidence is not None and confidence >= 0.6
        source_type = "image_pixels" if pixel_derived else "derived_heuristic"
        method = "track_color_vectorizer" if pixel_derived else "speed_heading_heuristic"
        fields += _insert_fields(
            conn,
            screenshot_id=sid,
            object_type="flight_track_feature",
            object_id=object_id,
            fields=zip(names, row[2:], strict=True),
            source_type=source_type,
            source_ref=f"screenshot_sha256:{shas.get(sid, 'unknown')}",
            method=method,
            confidence=confidence,
            validation_outcome="UNVERIFIED",
            observed_at=observed_at,
        )
        objects += 1
    return objects, fields


def _icons(
    conn: sqlite3.Connection,
    shas: dict[int, str],
    observed_at: str,
) -> tuple[int, int]:
    if not _table_exists(conn, "icon_observations"):
        return 0, 0
    objects = fields = 0
    rows = conn.execute(
        """SELECT icon_id, screenshot_id, pin_id, bbox_x, bbox_y, bbox_w,
                  bbox_h, centroid_x, centroid_y, area_px, aspect, fill_ratio,
                  hue_deg, saturation, value, ahash, cluster_id, icon_class,
                  confidence, review_status
           FROM icon_observations ORDER BY icon_id"""
    )
    names = (
        "pin_id",
        "bbox_x",
        "bbox_y",
        "bbox_w",
        "bbox_h",
        "centroid_x",
        "centroid_y",
        "area_px",
        "aspect",
        "fill_ratio",
        "hue_deg",
        "saturation",
        "value",
        "ahash",
        "cluster_id",
        "icon_class",
        "confidence",
        "review_status",
    )
    for row in rows:
        object_id, sid = int(row[0]), int(row[1])
        confidence = float(row[18]) if row[18] is not None else None
        fields += _insert_fields(
            conn,
            screenshot_id=sid,
            object_type="icon_observation",
            object_id=object_id,
            fields=zip(names, row[2:], strict=True),
            source_type="image_pixels",
            source_ref=f"screenshot_sha256:{shas.get(sid, 'unknown')}",
            method="adaptive_salience_icon_detector",
            confidence=confidence,
            validation_outcome="UNVERIFIED",
            observed_at=observed_at,
        )
        objects += 1
    return objects, fields


def _frames_and_gui(
    conn: sqlite3.Connection,
    sources: dict[int, dict[str, int]],
    observed_at: str,
) -> tuple[int, int]:
    objects = fields = 0
    if _table_exists(conn, "frame_observations"):
        rows = conn.execute(
            """SELECT frame_obs_id, screenshot_id, frame_type, provider,
                      orientation, confidence, classification_method,
                      review_status
               FROM frame_observations ORDER BY frame_obs_id"""
        )
        names = (
            "frame_type",
            "provider",
            "orientation",
            "confidence",
            "classification_method",
            "review_status",
        )
        for row in rows:
            object_id, sid = int(row[0]), int(row[1])
            confidence = float(row[5]) if row[5] is not None else None
            fields += _insert_fields(
                conn,
                screenshot_id=sid,
                object_type="frame_observation",
                object_id=object_id,
                fields=zip(names, row[2:], strict=True),
                source_type="ocr_observation",
                source_ref=_source_for(sources, sid, tuple()),
                method=str(row[6]),
                confidence=confidence,
                validation_outcome="UNVERIFIED",
                observed_at=observed_at,
            )
            objects += 1
    if _table_exists(conn, "gui_artifact_observations"):
        rows = conn.execute(
            """SELECT gui_artifact_id, screenshot_id, source_obs_id,
                      artifact_type, bbox_x, bbox_y, bbox_w, bbox_h, raw_text,
                      normalized_text, confidence, extraction_status,
                      review_status, method
               FROM gui_artifact_observations ORDER BY gui_artifact_id"""
        )
        names = (
            "source_obs_id",
            "artifact_type",
            "bbox_x",
            "bbox_y",
            "bbox_w",
            "bbox_h",
            "raw_text",
            "normalized_text",
            "confidence",
            "extraction_status",
            "review_status",
            "method",
        )
        for row in rows:
            object_id, sid = int(row[0]), int(row[1])
            source_obs_id = row[2]
            confidence = float(row[10]) if row[10] is not None else None
            fields += _insert_fields(
                conn,
                screenshot_id=sid,
                object_type="gui_artifact",
                object_id=object_id,
                fields=zip(names, row[2:], strict=True),
                source_type="ocr_observation",
                source_ref=(
                    f"ocr_observations:{source_obs_id}"
                    if source_obs_id is not None
                    else f"screenshot:{sid}"
                ),
                method=str(row[13]),
                confidence=confidence,
                validation_outcome=(
                    "UNVERIFIED" if row[11] != "failed" else "INVALID"
                ),
                observed_at=observed_at,
            )
            objects += 1
    return objects, fields


def _map_states(
    conn: sqlite3.Connection,
    observed_at: str,
) -> tuple[int, int]:
    if not _table_exists(conn, "map_state_observations"):
        return 0, 0
    objects = fields = 0
    rows = conn.execute(
        """SELECT map_state_id, screenshot_id, frame_obs_id, viewport_x,
                  viewport_y, viewport_w, viewport_h, center_lat, center_lon,
                  zoom, bearing_deg, extent_geojson, geolocation_status,
                  confidence, method
           FROM map_state_observations ORDER BY map_state_id"""
    )
    names = (
        "frame_obs_id",
        "viewport_x",
        "viewport_y",
        "viewport_w",
        "viewport_h",
        "center_lat",
        "center_lon",
        "zoom",
        "bearing_deg",
        "extent_geojson",
        "geolocation_status",
        "confidence",
        "method",
    )
    for row in rows:
        object_id, sid = int(row[0]), int(row[1])
        geolocation_status = str(row[12])
        has_coords = row[7] is not None or row[8] is not None or row[11] is not None
        outcome = (
            "CONFLICTED"
            if geolocation_status == "unsupported" and has_coords
            else "UNVERIFIED"
        )
        fields += _insert_fields(
            conn,
            screenshot_id=sid,
            object_type="map_state",
            object_id=object_id,
            fields=zip(names, row[2:], strict=True),
            source_type="derived_layout",
            source_ref=f"frame_observations:{row[2]}",
            method=str(row[14]),
            confidence=float(row[13]) if row[13] is not None else None,
            validation_outcome=outcome,
            observed_at=observed_at,
        )
        objects += 1
    return objects, fields


def _icon_artifacts(
    conn: sqlite3.Connection,
    shas: dict[int, str],
    observed_at: str,
) -> tuple[int, int]:
    if not _table_exists(conn, "icon_artifacts"):
        return 0, 0
    objects = fields = 0
    rows = conn.execute(
        """SELECT icon_artifact_id, screenshot_id, icon_id, source_sha256,
                  crop_rel_path, crop_sha256, capture_status, capture_error,
                  method
           FROM icon_artifacts ORDER BY icon_artifact_id"""
    )
    names = (
        "icon_id",
        "source_sha256",
        "crop_rel_path",
        "crop_sha256",
        "capture_status",
        "capture_error",
        "method",
    )
    for row in rows:
        object_id, sid = int(row[0]), int(row[1])
        outcome = "VALID" if row[6] == "ok" else "INVALID"
        fields += _insert_fields(
            conn,
            screenshot_id=sid,
            object_type="icon_artifact",
            object_id=object_id,
            fields=zip(names, row[2:], strict=True),
            source_type="image_crop",
            source_ref=f"screenshot_sha256:{shas.get(sid, 'unknown')}",
            method=str(row[8]),
            confidence=1.0 if outcome == "VALID" else 0.0,
            validation_outcome=outcome,
            observed_at=observed_at,
        )
        objects += 1
    return objects, fields


def run(db_path: Path = DB) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"RLSM DB not found: {db_path}")
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    ensure_schema(conn)

    observed_at = _iso_now()
    sources = _latest_ocr_sources(conn)
    shas = _screenshot_shas(conn)
    conn.execute("DELETE FROM extraction_field_provenance")
    conn.commit()

    results: dict[str, dict[str, int]] = {}
    handlers = (
        ("labeled_pins", lambda: _labels(conn, sources, observed_at)),
        ("aircraft", lambda: _aircraft(conn, sources, observed_at)),
        ("tracks", lambda: _tracks(conn, shas, observed_at)),
        ("icons", lambda: _icons(conn, shas, observed_at)),
        ("frames_gui", lambda: _frames_and_gui(conn, sources, observed_at)),
        ("map_states", lambda: _map_states(conn, observed_at)),
        ("icon_artifacts", lambda: _icon_artifacts(conn, shas, observed_at)),
    )
    total_objects = total_fields = 0
    with conn:
        for name, handler in handlers:
            objects, fields = handler()
            results[name] = {"objects": objects, "fields": fields}
            total_objects += objects
            total_fields += fields
    conn.close()
    return {
        "objects": total_objects,
        "fields": total_fields,
        "by_domain": results,
        "table": "extraction_field_provenance",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB)
    args = parser.parse_args(argv)
    try:
        result = run(args.db)
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
