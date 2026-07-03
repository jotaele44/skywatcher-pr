#!/usr/bin/env python3
"""Build the canonical airspace producer package from the FR24 SQLite pipeline DB.

This closes the automation gap between Stage B (fr24/event_export.py writes the
operational SQLite DB) and Stage D (scripts/validate_airspace_export.py /
scripts/federation_export.py consume a producer package): previously nothing
turned the real DB into `observations.geojson`, `observations.csv`,
`sources.json`, `lineage.json`, `confidence.json` + `manifest.json`, so even
with a real FlightRadar24 capture the production promotion was un-automated.

Reads the `screenshots` table (see fr24/screenshot_inventory.py) and emits one
observation per row that carries usable coordinates and a timestamp; rows
missing either are reported as skipped (they belong in the manual review
queue, not the export). Rows with review_status='rejected' are excluded.

Real captures produce rows with synthetic=false. The --mark-synthetic flag
exists ONLY so unit tests can exercise the builder against fabricated fixture
DBs without ever producing rows that could pass a production-mode validation.

Usage (operator, after a real capture is loaded into the DB):
    python scripts/build_producer_package.py --db data/operational/fr24.db \
        --out exports/fr24_package
    python scripts/validate_airspace_export.py exports/fr24_package --mode production
    python scripts/federation_export.py --package exports/fr24_package --mode production
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "priis.airspace_export.v0.1"
PRODUCER = "skywatcher-pr"
# fr24_exports is a T2 source in registry/source_registry.yaml.
EVIDENCE_TIER = "T2"
SIGNAL_TYPE = "FR24_SCREENSHOT"
LOCATED_CONFIDENCE_FLOOR = 0.8

CSV_FIELDS = [
    "observation_id", "event_datetime", "location_name", "municipality",
    "lat", "lon", "altitude_ft", "bearing", "duration_seconds", "signal_type",
    "description_summary", "source_id", "source_type", "evidence_tier",
    "confidence", "geometry_status", "temporal_status", "lineage_id", "synthetic",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_or_none(value: Any) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _blend_confidence(ocr: Optional[float], coord: Optional[float]) -> float:
    parts = [p for p in (ocr, coord) if isinstance(p, (int, float))]
    if not parts:
        return 0.5
    return round(max(0.0, min(1.0, sum(parts) / len(parts))), 3)


def read_screenshot_rows(db_path: Path) -> List[sqlite3.Row]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM screenshots WHERE COALESCE(review_status, 'pending') != 'rejected'"
            " ORDER BY screenshot_id"
        ).fetchall()
    finally:
        conn.close()


def build_records(
    rows: List[sqlite3.Row], *, mark_synthetic: bool = False
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    observations: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []
    lineage: List[Dict[str, Any]] = []
    confidence: List[Dict[str, Any]] = []
    skipped: List[str] = []

    for row in rows:
        sid = row["screenshot_id"]
        event_datetime = _iso_or_none(row["timestamp"])
        lat, lon = row["latitude"], row["longitude"]
        if event_datetime is None or lat is None or lon is None:
            skipped.append(f"{sid}: missing timestamp or coordinates (manual review)")
            continue

        observation_id = f"fr24-{sid}"
        source_id = f"src-{sid}"
        lineage_id = f"lin-{sid}"
        coord_conf = row["coordinate_confidence"]
        overall = _blend_confidence(row["ocr_confidence"], coord_conf)
        geometry_status = (
            "located"
            if isinstance(coord_conf, (int, float)) and coord_conf >= LOCATED_CONFIDENCE_FLOOR
            else "approximate"
        )

        observations.append({
            "observation_id": observation_id,
            "event_datetime": event_datetime,
            "location_name": "",
            "municipality": "",
            "lat": lat,
            "lon": lon,
            "altitude_ft": row["altitude_ft"],
            "bearing": "",
            "duration_seconds": "",
            "signal_type": SIGNAL_TYPE,
            "description_summary": (
                f"FR24 screenshot-derived observation (callsign {row['callsign'] or 'unknown'},"
                f" flight {row['flight_id'] or 'unknown'})"
            ),
            "source_id": source_id,
            "source_type": "screenshot",
            "evidence_tier": EVIDENCE_TIER,
            "confidence": overall,
            "geometry_status": geometry_status,
            "temporal_status": "exact",
            "lineage_id": lineage_id,
            "synthetic": bool(mark_synthetic),
        })
        sources.append({
            "source_id": source_id,
            "source_type": "screenshot",
            "source_path": row["image_path"],
            "sha256": row["sha256"] or "",
            "retrieved_at": _iso_or_none(row["processed_at"]) or event_datetime,
            "provenance_status": "synthetic_fixture" if mark_synthetic else "operator_capture",
        })
        lineage.append({
            "lineage_id": lineage_id,
            "observation_id": observation_id,
            "source_id": source_id,
            "pipeline_stage": "fr24_screenshot_ocr",
            "extraction_method": "ensemble_ocr",
            "coordinate_method": row["coordinate_method"] or "unknown",
            "notes": f"review_status={row['review_status'] or 'pending'}",
        })
        confidence.append({
            "observation_id": observation_id,
            "overall_confidence": overall,
            "field_confidence": {
                "event_datetime": 0.95,
                "lat": coord_conf if isinstance(coord_conf, (int, float)) else 0.5,
                "lon": coord_conf if isinstance(coord_conf, (int, float)) else 0.5,
                "signal_type": 0.9,
            },
        })

    return observations, sources, lineage, confidence, skipped


def write_package(
    out_dir: Path,
    observations: List[Dict[str, Any]],
    sources: List[Dict[str, Any]],
    lineage: List[Dict[str, Any]],
    confidence: List[Dict[str, Any]],
    *,
    mode: str,
    package_id: str,
) -> Dict[str, Any]:
    import csv

    out_dir.mkdir(parents=True, exist_ok=True)

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [o["lon"], o["lat"]]},
            "properties": dict(o),
        }
        for o in observations
    ]
    (out_dir / "observations.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2),
        encoding="utf-8",
    )
    with (out_dir / "observations.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for o in observations:
            writer.writerow({k: ("" if o.get(k) is None else o.get(k)) for k in CSV_FIELDS})
    (out_dir / "sources.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
    (out_dir / "lineage.json").write_text(json.dumps(lineage, indent=2), encoding="utf-8")
    (out_dir / "confidence.json").write_text(json.dumps(confidence, indent=2), encoding="utf-8")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "package_id": package_id,
        "created_at": _utc_now(),
        "mode": mode,
        "description": "Airspace producer package built from the FR24 screenshot pipeline DB.",
        "files": {
            "observations_geojson": "observations.geojson",
            "observations_csv": "observations.csv",
            "sources": "sources.json",
            "lineage": "lineage.json",
            "confidence": "confidence.json",
        },
        "record_counts": {
            "observations": len(observations),
            "sources": len(sources),
            "lineage": len(lineage),
            "confidence": len(confidence),
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build the airspace producer package from the FR24 DB.")
    ap.add_argument("--db", required=True, help="Path to the FR24 pipeline SQLite DB")
    ap.add_argument("--out", required=True, help="Output package directory")
    ap.add_argument("--mode", default="test", choices=["test", "production"])
    ap.add_argument("--package-id", default=None)
    ap.add_argument(
        "--mark-synthetic",
        action="store_true",
        help="Flag every row synthetic=true (unit-test fixtures only; such a "
        "package can never pass a production-mode validation)",
    )
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"FAIL — DB not found: {db_path}")
        return 1

    rows = read_screenshot_rows(db_path)
    observations, sources, lineage, confidence, skipped = build_records(
        rows, mark_synthetic=args.mark_synthetic
    )
    if not observations:
        print("FAIL — no exportable screenshot rows (all missing coords/timestamp or rejected)")
        return 1

    package_id = args.package_id or (
        f"fr24_package_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    manifest = write_package(
        Path(args.out), observations, sources, lineage, confidence,
        mode=args.mode, package_id=package_id,
    )
    for note in skipped:
        print(f"skipped {note}")
    print(
        f"wrote {args.out}/manifest.json — observations={manifest['record_counts']['observations']}"
        f" skipped={len(skipped)} mode={args.mode}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
