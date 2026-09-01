"""Offline ingestion of provider-neutral aviation vision results into RLSM.

The input is an ``aviation_vision_extraction.v1`` record produced outside
Skywatcher. This module never invokes a model or provider. It preserves every
field's provenance ID in append-only RLSM linkage rows.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any

ENGINE = "vision_result_v1"
ZONE = "vision_full_frame"
_ALLOWED_FIELDS = {
    "registration", "callsign", "aircraft_type", "operator", "origin",
    "destination", "timestamp", "latitude", "longitude", "altitude",
    "speed", "heading", "route_text", "other",
}
_ALLOWED_VALIDATION = {"VALID", "INVALID", "UNVERIFIED", "CONFLICTED"}
_ALLOWED_REVIEW = {"UNREVIEWED", "NEEDS_REVIEW", "APPROVED", "REJECTED", "SUPERSEDED"}

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS vision_extractions (
    extraction_id TEXT PRIMARY KEY,
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    ocr_obs_id INTEGER NOT NULL REFERENCES ocr_observations(obs_id),
    source_artifact_id TEXT NOT NULL,
    model_run_receipt_id TEXT NOT NULL,
    extraction_schema_version TEXT NOT NULL,
    review_status TEXT NOT NULL,
    provisional INTEGER NOT NULL CHECK (provisional = 1),
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_vision_extractions_screenshot
    ON vision_extractions(screenshot_id);
CREATE TABLE IF NOT EXISTS vision_field_provenance (
    provenance_link_id INTEGER PRIMARY KEY AUTOINCREMENT,
    extraction_id TEXT NOT NULL REFERENCES vision_extractions(extraction_id),
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    ocr_obs_id INTEGER NOT NULL REFERENCES ocr_observations(obs_id),
    field_name TEXT NOT NULL,
    field_value_json TEXT NOT NULL,
    provenance_id TEXT NOT NULL,
    validation_outcome TEXT NOT NULL,
    model_run_receipt_id TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    UNIQUE(extraction_id, field_name)
);
CREATE INDEX IF NOT EXISTS ix_vision_field_provenance_screenshot
    ON vision_field_provenance(screenshot_id, field_name);
"""


class VisionResultError(ValueError):
    """Raised when an extraction violates the provider-neutral contract."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def ensure_provenance_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)


def validate_extraction(record: Mapping[str, Any]) -> None:
    required = {
        "schema_version", "extraction_id", "source_artifact_id",
        "model_run_receipt_id", "extraction_schema_version", "fields",
        "review_status", "provisional",
    }
    missing = sorted(required - set(record))
    if missing:
        raise VisionResultError(f"missing extraction fields: {missing}")
    if record["schema_version"] != "aviation_vision_extraction.v1":
        raise VisionResultError("unsupported schema_version")
    if record["provisional"] is not True:
        raise VisionResultError("vision extraction must remain provisional")
    if record["review_status"] not in _ALLOWED_REVIEW:
        raise VisionResultError("unsupported review_status")
    if not str(record["extraction_id"]).strip():
        raise VisionResultError("extraction_id is required")
    if not str(record["source_artifact_id"]).strip():
        raise VisionResultError("source_artifact_id is required")
    if not str(record["model_run_receipt_id"]).strip():
        raise VisionResultError("model_run_receipt_id is required")
    fields = record["fields"]
    if not isinstance(fields, list) or not fields:
        raise VisionResultError("fields must be a non-empty list")
    seen: set[str] = set()
    for field in fields:
        if not isinstance(field, Mapping):
            raise VisionResultError("each field must be an object")
        field_required = {"field_name", "value", "provenance_id", "validation_outcome"}
        field_missing = sorted(field_required - set(field))
        if field_missing:
            raise VisionResultError(f"missing field properties: {field_missing}")
        name = str(field["field_name"])
        if name not in _ALLOWED_FIELDS:
            raise VisionResultError(f"unsupported field_name: {name}")
        if name in seen:
            raise VisionResultError(f"duplicate field_name: {name}")
        seen.add(name)
        if not str(field["provenance_id"]).strip():
            raise VisionResultError(f"provenance_id is required for {name}")
        if field["validation_outcome"] not in _ALLOWED_VALIDATION:
            raise VisionResultError(f"unsupported validation_outcome for {name}")


def _artifact_sha(source_artifact_id: str) -> str:
    value = source_artifact_id.strip()
    return value[7:] if value.startswith("sha256:") else value


def resolve_screenshot_id(
    conn: sqlite3.Connection,
    source_artifact_id: str,
    artifact_lookup: Mapping[str, int] | None = None,
) -> int | None:
    if artifact_lookup and source_artifact_id in artifact_lookup:
        return int(artifact_lookup[source_artifact_id])
    row = conn.execute(
        "SELECT screenshot_id FROM screenshots WHERE sha256 = ?",
        (_artifact_sha(source_artifact_id),),
    ).fetchone()
    return int(row[0]) if row else None


def _field_map(record: Mapping[str, Any]) -> dict[str, Any]:
    return {str(field["field_name"]): field["value"] for field in record["fields"]}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _insert_extraction(
    conn: sqlite3.Connection,
    record: Mapping[str, Any],
    screenshot_id: int,
    observed_at: str,
) -> tuple[int, bool]:
    field_values = _field_map(record)
    raw_payload = canonical_json(record)
    cursor = conn.execute(
        "INSERT INTO ocr_observations (screenshot_id, zone, raw_text, raw_lines_json,"
        " engine, engine_version, ocr_status, observed_at) VALUES (?, ?, ?, ?, ?, ?, 'ok', ?)",
        (
            screenshot_id,
            ZONE,
            canonical_json(field_values),
            raw_payload,
            ENGINE,
            str(record["extraction_schema_version"]),
            observed_at,
        ),
    )
    ocr_obs_id = int(cursor.lastrowid)
    conn.execute(
        "INSERT INTO vision_extractions (extraction_id, screenshot_id, ocr_obs_id,"
        " source_artifact_id, model_run_receipt_id, extraction_schema_version,"
        " review_status, provisional, observed_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
        (
            str(record["extraction_id"]), screenshot_id, ocr_obs_id,
            str(record["source_artifact_id"]), str(record["model_run_receipt_id"]),
            str(record["extraction_schema_version"]), str(record["review_status"]),
            observed_at,
        ),
    )
    for field in record["fields"]:
        conn.execute(
            "INSERT INTO vision_field_provenance (extraction_id, screenshot_id, ocr_obs_id,"
            " field_name, field_value_json, provenance_id, validation_outcome,"
            " model_run_receipt_id, source_artifact_id, observed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(record["extraction_id"]), screenshot_id, ocr_obs_id,
                str(field["field_name"]), canonical_json(field["value"]),
                str(field["provenance_id"]), str(field["validation_outcome"]),
                str(record["model_run_receipt_id"]), str(record["source_artifact_id"]),
                observed_at,
            ),
        )

    registration = str(field_values.get("registration") or "").strip().upper() or None
    callsign = str(field_values.get("callsign") or "").strip() or None
    inserted_aircraft = False
    if registration or callsign:
        excerpt = {
            "extraction_id": record["extraction_id"],
            "model_run_receipt_id": record["model_run_receipt_id"],
            "fields": record["fields"],
        }
        before = conn.total_changes
        conn.execute(
            "INSERT OR IGNORE INTO aircraft_observations"
            " (screenshot_id, registration, callsign, aircraft_type, altitude_ft, speed_kt,"
            " heading_deg, operator_text, identity_status, source_zone, raw_excerpt, observed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'recovered', ?, ?, ?)",
            (
                screenshot_id, registration, callsign,
                str(field_values.get("aircraft_type") or "").strip() or None,
                _int_or_none(field_values.get("altitude")),
                _int_or_none(field_values.get("speed")),
                _int_or_none(field_values.get("heading")),
                str(field_values.get("operator") or "").strip() or None,
                ZONE, canonical_json(excerpt), observed_at,
            ),
        )
        inserted_aircraft = conn.total_changes > before
    return ocr_obs_id, inserted_aircraft


def ingest_extractions(
    conn: sqlite3.Connection,
    records: Iterable[Mapping[str, Any]],
    *,
    observed_at: str,
    dry_run: bool = False,
    artifact_lookup: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Validate and ingest records with deterministic, append-only idempotence."""
    materialized = list(records)
    stats: dict[str, Any] = {
        "inputs": len(materialized),
        "inserted": 0,
        "aircraft_rows_inserted": 0,
        "skipped_existing": 0,
        "unmatched": 0,
        "failed": 0,
        "failures": [],
        "dry_run": bool(dry_run),
    }
    if not dry_run:
        ensure_provenance_tables(conn)
    for index, record in enumerate(materialized):
        extraction_id = str(record.get("extraction_id") or f"input-{index}")
        try:
            validate_extraction(record)
            screenshot_id = resolve_screenshot_id(
                conn, str(record["source_artifact_id"]), artifact_lookup
            )
            if screenshot_id is None:
                stats["unmatched"] += 1
                stats["failures"].append({
                    "extraction_id": extraction_id,
                    "reason": "source_artifact_not_matched",
                })
                continue
            if not dry_run:
                existing = conn.execute(
                    "SELECT 1 FROM vision_extractions WHERE extraction_id = ?",
                    (extraction_id,),
                ).fetchone()
                if existing:
                    stats["skipped_existing"] += 1
                    continue
                with conn:
                    _, inserted_aircraft = _insert_extraction(
                        conn, record, screenshot_id, observed_at
                    )
                stats["aircraft_rows_inserted"] += int(inserted_aircraft)
            stats["inserted"] += 1
        except (VisionResultError, sqlite3.DatabaseError) as exc:
            stats["failed"] += 1
            stats["failures"].append({
                "extraction_id": extraction_id,
                "reason": str(exc),
            })
    return stats
