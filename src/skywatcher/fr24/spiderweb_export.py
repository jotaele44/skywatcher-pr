"""SPIDERWEB BRIDGE EXPORT (mission responsibility 18 + Phase 6)

Serializes validated Skywatcher flights into ``spiderweb_bridge`` records and a
hub-canonical package manifest that Spiderweb's ``--ingest-skywatcher`` adapter
consumes.

This module encodes the contradiction resolutions in one place:
    * confidence  -> {"score", "method"}                     (C3)
    * review_status crosswalked to the Spiderweb vocabulary   (C4)
    * coordinate_method uses the widened enum                 (C5)
    * mission_classification is OPTIONAL and gated            (C1)
    * generated_at_utc is the canonical timestamp name        (C7)
    * terminal-accept labels ('confirmed') never emitted      (C2)

``build_bridge_record`` is pure and unit-testable with synthetic dicts (no DB).
``export_package`` reads an existing database read-only; it is exercised in tests
against a temporary synthetic DB and is never run against operational data as
part of the repository-boundary task.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from . import database as db
from . import mission_classification as mc
from . import review_status as rs
from . import telemetry_validation as tv

__all__ = [
    "BRIDGE_SCHEMA_VERSION",
    "BRIDGE_SCHEMA_PATH",
    "load_bridge_schema",
    "make_export_id",
    "build_bridge_record",
    "validate_bridge_record",
    "export_package",
]

BRIDGE_SCHEMA_VERSION = "1.0"
BRIDGE_SCHEMA_PATH = db.REPO_ROOT / "schemas" / "spiderweb_bridge.schema.json"
_DEFAULT_CONFIDENCE_METHOD = "skywatcher_fr24_fusion"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_bridge_schema() -> Dict[str, Any]:
    return json.loads(BRIDGE_SCHEMA_PATH.read_text(encoding="utf-8"))


def make_export_id(source_snapshot_id: str, generated_at_utc: str) -> str:
    """Deterministic hub-style package id: pkg_ + 32 hex chars."""
    digest = hashlib.md5(  # noqa: S324 - id derivation, not security
        f"{source_snapshot_id}|{generated_at_utc}".encode("utf-8")
    ).hexdigest()
    return f"pkg_{digest}"


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _line_string(track_points: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    coords: List[List[float]] = []
    for tp in track_points:
        lon = _as_float(tp.get("longitude"))
        lat = _as_float(tp.get("latitude"))
        if lon is None or lat is None:
            continue
        coords.append([lon, lat])  # GeoJSON order: [lon, lat]
    if len(coords) < 2:
        return None
    return {"type": "LineString", "coordinates": coords}


def build_bridge_record(
    flight: Dict[str, Any],
    track_points: Optional[List[Dict[str, Any]]] = None,
    *,
    export_id: str,
    source_snapshot_id: str,
    generated_at_utc: str,
    anomaly_flags: Optional[List[Dict[str, Any]]] = None,
    lineage: Optional[List[Dict[str, Any]]] = None,
    schema_version: str = BRIDGE_SCHEMA_VERSION,
) -> Dict[str, Any]:
    """Build a single ``spiderweb_bridge`` record from a flight row (pure)."""
    track_points = track_points or []
    confidence_score = _as_float(flight.get("confidence"))
    if confidence_score is None:
        confidence_score = 0.0
    confidence_score = max(0.0, min(1.0, confidence_score))

    # Gated mission classification (never a Skywatcher-confirmed fact).
    mission = None
    if flight.get("mission_type"):
        gated = mc.classify(
            flight.get("mission_type"),
            _as_float(flight.get("mission_confidence")) or 0.0,
        )
        mission = gated.to_dict()

    interval = None
    if flight.get("takeoff_time") or flight.get("landing_time"):
        interval = {"start": flight.get("takeoff_time"), "end": flight.get("landing_time")}

    # Bridge `aircraft_id` is a string|null (registration preferred). `flights`
    # links to the canonical `aircraft` table via an INTEGER FK, so coerce any
    # numeric id to a string to satisfy the schema (contradiction: FK int vs
    # bridge string).
    _aid = flight.get("registration") or flight.get("aircraft_id")
    aircraft_id = str(_aid) if _aid is not None and str(_aid) != "" else None

    record: Dict[str, Any] = {
        "schema_version": schema_version,
        "export_id": export_id,
        "generated_at_utc": generated_at_utc,
        "source_snapshot_id": source_snapshot_id,
        "flight_id": str(flight.get("flight_id")),
        "aircraft_id": aircraft_id,
        "validated_time_interval": interval,
        "validated_track_geometry": _line_string(track_points),
        "mission_classification": mission,
        "anomaly_flags": anomaly_flags or [],
        "confidence": {"score": confidence_score, "method": _DEFAULT_CONFIDENCE_METHOD},
        "review_status": rs.to_spiderweb_review_status(flight.get("review_status") or "draft"),
        "coordinate_method": flight.get("coordinate_method"),
        "provenance": {
            "source_id": source_snapshot_id,
            "lineage": lineage or [{"step": "skywatcher_fr24_export", "actor": "skywatcher-pr", "ts": generated_at_utc}],
        },
    }
    return record


def _iso_ok(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _datetime_problems(record: Dict[str, Any]) -> List[str]:
    """Deterministic ISO-8601 checks for the date-time fields (jsonschema's
    `format` assertions are advisory and need a backing lib, so we verify here)."""
    problems: List[str] = []
    if not _iso_ok(record.get("generated_at_utc")):
        problems.append("generated_at_utc: not an ISO-8601 datetime")
    interval = record.get("validated_time_interval") or {}
    for k in ("start", "end"):
        if not _iso_ok(interval.get(k)):
            problems.append(f"validated_time_interval.{k}: not an ISO-8601 datetime")
    return problems


def validate_bridge_record(record: Dict[str, Any]) -> List[str]:
    """Validate a bridge record against the shared schema + datetime formats
    (empty == valid)."""
    return tv.validate_against_schema(record, load_bridge_schema()) + _datetime_problems(record)


def export_package(
    db_path: Union[str, Path],
    out_dir: Union[str, Path],
    *,
    source_snapshot_id: Optional[str] = None,
    mode: str = "test",
    generated_at_utc: Optional[str] = None,
) -> str:
    """Read flights from ``db_path`` (read-only) and write a bridge package to
    ``out_dir`` (bridge JSONL + manifest). Returns ``out_dir``.

    Every record is schema-validated before being written; an invalid record
    raises ValueError (fail closed). Empty exports are written but reported with
    a zero count in the manifest (never silently reported as success elsewhere).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    generated_at_utc = generated_at_utc or _utc_now_iso()
    source_snapshot_id = source_snapshot_id or f"skywatcher::{Path(db_path).stem}"
    export_id = make_export_id(source_snapshot_id, generated_at_utc)

    conn = db.connect(db_path, create_parent=False)
    records: List[Dict[str, Any]] = []
    try:
        # LEFT JOIN aircraft so the bridge can carry the registration string
        # rather than the integer FK (see build_bridge_record).
        flight_rows = conn.execute(
            "SELECT f.*, a.registration AS registration "
            "FROM flights f LEFT JOIN aircraft a ON a.aircraft_id = f.aircraft_id"
        ).fetchall()
        for fr in flight_rows:
            flight = dict(fr)
            tps = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM track_points WHERE flight_id = ? ORDER BY seq",
                    (flight["flight_id"],),
                ).fetchall()
            ]
            rec = build_bridge_record(
                flight,
                tps,
                export_id=export_id,
                source_snapshot_id=source_snapshot_id,
                generated_at_utc=generated_at_utc,
            )
            problems = validate_bridge_record(rec)
            if problems:
                raise ValueError(f"bridge record for {flight['flight_id']} invalid: {problems}")
            records.append(rec)
    finally:
        conn.close()

    records_path = out / "bridge_records.jsonl"
    with records_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")

    manifest = {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "export_id": export_id,
        "producer": "skywatcher-pr",
        "generated_at_utc": generated_at_utc,
        "mode": mode,
        "source_snapshot_id": source_snapshot_id,
        "bridge_schema": "spiderweb_bridge",
        "files": {"bridge_records": "bridge_records.jsonl"},
        "record_counts": {"flights": len(records)},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return str(out)
