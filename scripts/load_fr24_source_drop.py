#!/usr/bin/env python3
"""Load certified FR24 source-drop CSVs into a runtime FR24 SQLite DB.

This bridges the local FR24 media/observation evidence into the existing
scripts/build_producer_package.py contract. It never fabricates coordinates:
rows without real lat/lon stay non-exportable and are counted for review.
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
) -> dict[str, Any]:
    init = initialize_database(db_path)
    if init.problems:
        raise RuntimeError("; ".join(init.problems))

    media_rows = read_csv(media_index)
    obs_rows = read_csv(observations)
    review_rows = read_csv(review) if review.exists() else []
    media_by_name = best_media_by_filename(media_rows)

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
                "Loaded certified FR24 media and aircraft observation CSVs; no coordinate fabrication.",
            ),
        )
        batch_id = int(cur.lastrowid)

        inserted = 0
        missing_geometry = 0
        missing_media_sha = 0
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
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO screenshots (
                    sha256, filename, rel_path, source_ref, month_bucket, filename_ts,
                    ext, size_bytes, ingest_status, ocr_status, review_status, batch_id,
                    ingested_at, image_path, flight_id, processed_at, callsign,
                    altitude_ft, ground_speed_mph, latitude, longitude, timestamp,
                    raw_text, ocr_confidence, coordinate_method, coordinate_confidence,
                    estimated_error_m
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    "source_drop_coordinates" if lat is not None and lon is not None else "unknown",
                    0.8 if lat is not None and lon is not None else None,
                    None,
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
            "exportable_rows": len(obs_rows) - missing_geometry,
            "blocker_classification": "FOUND" if missing_geometry == 0 and obs_rows else "BLOCKED",
            "blocker_reason": (
                "FR24 rows include real coordinates."
                if missing_geometry == 0 and obs_rows
                else "FR24 rows lack real latitude/longitude; non-synthetic export must not fabricate coordinates."
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
    parser.add_argument("--summary-out", default=str(REPO_ROOT / "reports" / "source_drops" / "fr24_source_drop_load_summary.json"))
    parser.add_argument("--source-ref", default="fr24_source_drop_20260827")
    args = parser.parse_args()

    summary = load_source_drop(
        db_path=Path(args.db),
        media_index=Path(args.media_index),
        observations=Path(args.observations),
        review=Path(args.review),
        source_ref=args.source_ref,
    )
    out = Path(args.summary_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
