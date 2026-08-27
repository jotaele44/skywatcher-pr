#!/usr/bin/env python3
"""Load certified FR24 source-drop CSVs into a runtime FR24 SQLite DB.

This bridges the local FR24 media/observation evidence into the existing
scripts/build_producer_package.py contract. It never fabricates exact
coordinates: rows without source lat/lon only become exportable when a reviewer
provides a georeferenced screenshot bbox plus a visible aircraft icon pixel,
which is stored as an approximate, uncertainty-bounded point.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from skywatcher.fr24.database_migrations import initialize_database

DEFAULT_MEDIA_INDEX = Path("/Users/jotaele/Documents/FR24/FR24_DataBank/Media_Canonical/freeze_final/final_active_media_index.csv")
DEFAULT_OBSERVATIONS = Path("/Users/jotaele/Documents/Financials/Consolidated/entities/aircraft_observations.csv")
DEFAULT_REVIEW = Path("/Users/jotaele/Documents/Financials/Consolidated/entities/manual_review_aircraft_identity.csv")

COMPAT_COLUMNS: dict[str, str] = {
    "image_path": "TEXT",
    "flight_id": "TEXT",
    "processed_at": "TEXT",
    "callsign": "TEXT",
    "altitude_ft": "INTEGER",
    "ground_speed_mph": "INTEGER",
    "latitude": "REAL",
    "longitude": "REAL",
    "timestamp": "TEXT",
    "raw_text": "TEXT",
    "ocr_confidence": "REAL",
    "coordinate_method": "TEXT",
    "coordinate_confidence": "REAL",
    "estimated_error_m": "REAL",
    "aircraft_point_status": "TEXT",
    "aircraft_point_method": "TEXT",
    "aircraft_icon_visibility": "TEXT",
    "capture_bbox_geojson": "TEXT",
    "capture_geometry_method": "TEXT",
    "capture_geometry_confidence": "REAL",
    "capture_geometry_uncertainty_m": "REAL",
    "control_point_count": "INTEGER",
    "control_point_residual_px": "REAL",
    "position_precision": "TEXT",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def to_int(value: Any) -> int | None:
    try:
        text = str(value).strip().replace(",", "")
        return int(float(text)) if text else None
    except (TypeError, ValueError):
        return None


def to_float_0_1(value: Any) -> float | None:
    try:
        text = str(value).strip().replace("%", "")
        if not text:
            return None
        val = float(text)
        if val > 1:
            val = val / 100.0
        return max(0.0, min(1.0, val))
    except (TypeError, ValueError):
        return None


def to_float(value: Any) -> float | None:
    try:
        text = str(value).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def first_present(row: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return ""


def _norm_key(value: str | None) -> str:
    return Path(str(value or "").strip()).name.lower()


def _valid_bbox(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> bool:
    return -180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90


def _bbox_geojson(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> str:
    return json.dumps(
        {
            "type": "Polygon",
            "coordinates": [[
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat],
            ]],
        },
        separators=(",", ":"),
    )


def load_capture_review(path: Path | None) -> tuple[dict[str, dict[str, str]], int]:
    """Load reviewer-supplied capture geometry rows keyed by filename or sha256."""
    if path is None or not path.exists():
        return {}, 0
    out: dict[str, dict[str, str]] = {}
    rows = read_csv(path)
    for row in rows:
        for key in (row.get("filename"), row.get("sha256")):
            normalized = _norm_key(key)
            if normalized:
                out[normalized] = row
    return out, len(rows)


def derive_icon_point(row: dict[str, str]) -> dict[str, Any]:
    """Derive an approximate aircraft point from bbox + visible icon pixel."""
    visibility = (row.get("aircraft_icon_visibility") or "").strip().lower()
    if visibility != "visible":
        return {"status": "UNRESOLVED", "reason": "aircraft icon is not marked visible"}

    min_lon = to_float(first_present(row, ("capture_bbox_min_lon", "bbox_min_lon", "min_lon")))
    min_lat = to_float(first_present(row, ("capture_bbox_min_lat", "bbox_min_lat", "min_lat")))
    max_lon = to_float(first_present(row, ("capture_bbox_max_lon", "bbox_max_lon", "max_lon")))
    max_lat = to_float(first_present(row, ("capture_bbox_max_lat", "bbox_max_lat", "max_lat")))
    width = to_float(first_present(row, ("image_width", "width", "viewport_w")))
    height = to_float(first_present(row, ("image_height", "height", "viewport_h")))
    icon_x = to_float(first_present(row, ("aircraft_icon_pixel_x", "icon_pixel_x", "pixel_x")))
    icon_y = to_float(first_present(row, ("aircraft_icon_pixel_y", "icon_pixel_y", "pixel_y")))
    uncertainty = to_float(first_present(row, (
        "aircraft_point_uncertainty_m", "capture_geometry_uncertainty_m", "uncertainty_m"
    )))
    confidence = to_float_0_1(first_present(row, (
        "aircraft_point_confidence", "capture_geometry_confidence", "confidence"
    )))

    required = (min_lon, min_lat, max_lon, max_lat, width, height, icon_x, icon_y, uncertainty)
    if any(value is None for value in required):
        return {"status": "UNRESOLVED", "reason": "missing bbox, dimensions, icon pixel, or uncertainty"}
    assert min_lon is not None and min_lat is not None and max_lon is not None and max_lat is not None
    assert width is not None and height is not None and icon_x is not None and icon_y is not None
    assert uncertainty is not None
    if not _valid_bbox(min_lon, min_lat, max_lon, max_lat):
        return {"status": "UNRESOLVED", "reason": "invalid capture bbox"}
    if width <= 0 or height <= 0 or not (0 <= icon_x <= width) or not (0 <= icon_y <= height):
        return {"status": "UNRESOLVED", "reason": "invalid image dimensions or icon pixel"}
    if uncertainty <= 0:
        return {"status": "UNRESOLVED", "reason": "uncertainty must be positive"}

    lon = min_lon + (icon_x / width) * (max_lon - min_lon)
    lat = max_lat - (icon_y / height) * (max_lat - min_lat)
    return {
        "status": "ICON_DERIVED_APPROX",
        "lat": lat,
        "lon": lon,
        "confidence": confidence if confidence is not None else 0.65,
        "uncertainty_m": uncertainty,
        "bbox_geojson": _bbox_geojson(min_lon, min_lat, max_lon, max_lat),
        "capture_method": first_present(row, ("capture_geometry_method", "bbox_method")) or "reviewer_georeferenced_bbox",
        "point_method": first_present(row, ("aircraft_point_method", "icon_method")) or "screenshot_icon_georeference",
        "control_point_count": to_int(first_present(row, ("control_point_count", "anchor_count"))),
        "control_point_residual_px": to_float(first_present(row, ("control_point_residual_px", "fit_residual_px"))),
    }


def ensure_compat_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(screenshots)").fetchall()}
    for name, ddl_type in COMPAT_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE screenshots ADD COLUMN {name} {ddl_type}")


def create_review_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_drop_review (
            review_id TEXT PRIMARY KEY,
            screenshot_id TEXT,
            reason TEXT,
            severity TEXT,
            review_status TEXT,
            source_ref TEXT,
            observed_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_drop_load_summary (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


def best_media_by_filename(media_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row in media_rows:
        filename = Path(row.get("path", "")).name
        if filename:
            out.setdefault(filename, row)
    return out


def load_source_drop(
    *,
    db_path: Path,
    media_index: Path,
    observations: Path,
    review: Path,
    source_ref: str,
    capture_review: Path | None = None,
) -> dict[str, Any]:
    init = initialize_database(db_path)
    if init.problems:
        raise RuntimeError("; ".join(init.problems))

    media_rows = read_csv(media_index)
    obs_rows = read_csv(observations)
    review_rows = read_csv(review) if review.exists() else []
    media_by_name = best_media_by_filename(media_rows)
    capture_rows, capture_review_row_count = load_capture_review(capture_review)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        ensure_compat_columns(conn)
        create_review_tables(conn)
        now = utc_now()
        cur = conn.execute(
            "INSERT INTO ingestion_batches (batch_kind, source_ref, started_at, ended_at, status, n_inputs, n_processed, n_failed, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "fr24_source_drop",
                source_ref,
                now,
                now,
                "completed",
                len(media_rows) + len(obs_rows),
                0,
                0,
                "Loaded certified FR24 media and aircraft observation CSVs; exact coordinates are never fabricated.",
            ),
        )
        batch_id = int(cur.lastrowid)

        inserted = 0
        missing_geometry = 0
        missing_media_sha = 0
        source_coordinate_rows = 0
        icon_derived_rows = 0
        unresolved_capture_review_rows = 0
        for obs in obs_rows:
            filename = obs.get("filename") or f"aircraft_obs_{obs.get('aircraft_obs_id', inserted + 1)}"
            media = media_by_name.get(filename, {})
            sha = media.get("sha256") or f"missing-sha-{obs.get('aircraft_obs_id', inserted + 1)}"
            if not media:
                missing_media_sha += 1
            timestamp = obs.get("filename_ts") or obs.get("observed_at") or now
            confidence = to_float_0_1(obs.get("confidence"))
            altitude = to_int(obs.get("altitude_ft"))
            speed_kt = to_int(obs.get("speed_kt"))
            speed_mph = int(round(speed_kt * 1.15078)) if speed_kt is not None else None
            lat = to_float(first_present(obs, ("latitude", "lat", "position_lat")))
            lon = to_float(first_present(obs, ("longitude", "lon", "lng", "position_lon")))
            point_status = "SOURCE_PROVIDED" if lat is not None and lon is not None else "UNRESOLVED"
            point_method = "source_drop_coordinates" if lat is not None and lon is not None else "unknown"
            icon_visibility = ""
            bbox_geojson = None
            capture_method = ""
            capture_confidence = None
            capture_uncertainty_m = None
            control_point_count = None
            control_point_residual_px = None
            precision = "SOURCE_PROVIDED" if lat is not None and lon is not None else "UNRESOLVED"
            if lat is not None and lon is not None:
                source_coordinate_rows += 1
            else:
                review_row = (
                    capture_rows.get(_norm_key(filename))
                    or capture_rows.get(_norm_key(sha))
                    or {}
                )
                if review_row:
                    icon_visibility = (review_row.get("aircraft_icon_visibility") or "").strip().lower()
                    derived = derive_icon_point(review_row)
                    if derived["status"] == "ICON_DERIVED_APPROX":
                        lat = derived["lat"]
                        lon = derived["lon"]
                        point_status = "ICON_DERIVED_APPROX"
                        point_method = derived["point_method"]
                        confidence = min(
                            confidence if confidence is not None else 0.65,
                            derived["confidence"],
                        )
                        bbox_geojson = derived["bbox_geojson"]
                        capture_method = derived["capture_method"]
                        capture_confidence = derived["confidence"]
                        capture_uncertainty_m = derived["uncertainty_m"]
                        control_point_count = derived["control_point_count"]
                        control_point_residual_px = derived["control_point_residual_px"]
                        precision = "APPROXIMATE"
                        icon_derived_rows += 1
                    else:
                        unresolved_capture_review_rows += 1
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO screenshots (
                    sha256, filename, rel_path, source_ref, month_bucket, filename_ts,
                    ext, size_bytes, ingest_status, ocr_status, review_status, batch_id,
                    ingested_at, image_path, flight_id, processed_at, callsign,
                    altitude_ft, ground_speed_mph, latitude, longitude, timestamp,
                    raw_text, ocr_confidence, coordinate_method, coordinate_confidence,
                    estimated_error_m, aircraft_point_status, aircraft_point_method,
                    aircraft_icon_visibility, capture_bbox_geojson, capture_geometry_method,
                    capture_geometry_confidence, capture_geometry_uncertainty_m,
                    control_point_count, control_point_residual_px, position_precision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sha,
                    filename,
                    media.get("path") or filename,
                    source_ref,
                    media.get("date_bucket") or "",
                    timestamp,
                    Path(filename).suffix.lower() or ".unknown",
                    to_int(media.get("size")) or 0,
                    "ok",
                    "ok" if obs.get("raw_excerpt") else "partial",
                    "approved" if obs.get("identity_status") == "confirmed" else "pending",
                    batch_id,
                    now,
                    media.get("path") or filename,
                    obs.get("callsign") or obs.get("registration") or "",
                    obs.get("observed_at") or now,
                    obs.get("callsign") or obs.get("registration") or "",
                    altitude,
                    speed_mph,
                    lat,
                    lon,
                    timestamp,
                    obs.get("raw_excerpt") or "",
                    confidence,
                    point_method,
                    0.8 if point_status == "SOURCE_PROVIDED" else capture_confidence,
                    capture_uncertainty_m if point_status == "ICON_DERIVED_APPROX" else None,
                    point_status,
                    point_method,
                    icon_visibility,
                    bbox_geojson,
                    capture_method,
                    capture_confidence,
                    capture_uncertainty_m,
                    control_point_count,
                    control_point_residual_px,
                    precision,
                ),
            )
            inserted += max(cursor.rowcount, 0)
            if lat is None or lon is None:
                missing_geometry += 1

        for row in review_rows:
            conn.execute(
                "INSERT OR REPLACE INTO source_drop_review VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("review_id") or f"review-{row.get('screenshot_id', '')}",
                    row.get("screenshot_id", ""),
                    row.get("reason", ""),
                    row.get("severity", ""),
                    row.get("review_status", ""),
                    source_ref,
                    now,
                ),
            )

        summary = {
            "db_path": str(db_path),
            "batch_id": batch_id,
            "media_rows": len(media_rows),
            "aircraft_observation_rows": len(obs_rows),
            "manual_review_rows": len(review_rows),
            "screenshots_inserted_or_seen": inserted,
            "missing_media_sha_rows": missing_media_sha,
            "missing_geometry_rows": missing_geometry,
            "source_coordinate_rows": source_coordinate_rows,
            "capture_review_rows": capture_review_row_count,
            "capture_review_lookup_keys": len(capture_rows),
            "icon_derived_approx_rows": icon_derived_rows,
            "unresolved_capture_review_rows": unresolved_capture_review_rows,
            "exportable_rows": len(obs_rows) - missing_geometry,
            "blocker_classification": (
                "FOUND" if missing_geometry == 0 and obs_rows
                else "PARTIAL" if icon_derived_rows or source_coordinate_rows
                else "BLOCKED"
            ),
            "blocker_reason": (
                "FR24 rows include source or audited screenshot-derived approximate coordinates."
                if missing_geometry == 0 and obs_rows
                else "Only rows with source coordinates or audited visible-icon screenshot geometry are exportable; remaining rows stay review-bound."
                if icon_derived_rows or source_coordinate_rows
                else "FR24 rows lack source coordinates and no audited visible-icon screenshot geometry was supplied."
            ),
        }
        conn.executemany(
            "INSERT OR REPLACE INTO source_drop_load_summary (key, value) VALUES (?, ?)",
            [(k, json.dumps(v, sort_keys=True)) for k, v in summary.items()],
        )
        conn.commit()
        return summary
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(REPO_ROOT / "data" / "operational" / "fr24_source_drop.sqlite"))
    parser.add_argument("--media-index", default=str(DEFAULT_MEDIA_INDEX))
    parser.add_argument("--observations", default=str(DEFAULT_OBSERVATIONS))
    parser.add_argument("--review", default=str(DEFAULT_REVIEW))
    parser.add_argument("--capture-review", default=None)
    parser.add_argument("--summary-out", default=str(REPO_ROOT / "reports" / "source_drops" / "fr24_source_drop_load_summary.json"))
    parser.add_argument("--source-ref", default="fr24_source_drop_20260827")
    args = parser.parse_args()

    summary = load_source_drop(
        db_path=Path(args.db),
        media_index=Path(args.media_index),
        observations=Path(args.observations),
        review=Path(args.review),
        capture_review=Path(args.capture_review) if args.capture_review else None,
        source_ref=args.source_ref,
    )
    out = Path(args.summary_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
