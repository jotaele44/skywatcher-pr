"""Tests for strategy #2 — unifying the three screenshot lanes on the RLSM store.

Covers:
  - scripts/ingest_vision_csv_to_rlsm.py (vision CSV -> ocr_observations +
    aircraft_observations, idempotent, filename/month_dir matching)
  - scripts/build_producer_package.py --rlsm-db enrichment (FAA registry
    identity in the description; per-screenshot affine lifting a
    fixed_pr_bounds row over the `located` floor) and that the flag-less
    path is unchanged.
"""
from __future__ import annotations

import csv
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from integration.geo_calibration import GeoCalibration, apply_affine

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = REPO_ROOT / "data" / "rlsm" / "schema.sql"
INGESTER = REPO_ROOT / "scripts" / "ingest_vision_csv_to_rlsm.py"
BUILDER = REPO_ROOT / "scripts" / "build_producer_package.py"

TRUE_AFFINE = (-67.3, 0.001, 18.6, -0.0005)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))


@pytest.fixture
def rlsm_db(tmp_path: Path) -> Path:
    if not SCHEMA_SQL.exists():
        pytest.skip("data/rlsm/schema.sql not tracked")
    db = tmp_path / "rlsm.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript(SCHEMA_SQL.read_text())
    screenshots = [
        # (sid, sha, filename, rel_path)
        (1, "a" * 64, "2026-03-24 09-40-01.HEIC", "2026-03/2026-03-24 09-40-01.HEIC"),
        (2, "b" * 64, "2026-04-02 10-00-00.HEIC", "2026-04/2026-04-02 10-00-00.HEIC"),
        # 3 + 4 share a basename across month dirs (disambiguated by month_dir)
        (3, "c" * 64, "dup.HEIC", "2026-05/dup.HEIC"),
        (4, "d" * 64, "dup.HEIC", "2026-06/dup.HEIC"),
    ]
    for sid, sha, filename, rel_path in screenshots:
        conn.execute(
            "INSERT INTO screenshots (screenshot_id, sha256, filename, rel_path, ext,"
            " size_bytes, width, height, ingest_status, ingested_at)"
            " VALUES (?, ?, ?, ?, 'heic', 1000, 1170, 2532, 'ok', '2026-06-01T00:00:00Z')",
            (sid, sha, filename, rel_path),
        )
    # Calibration anchors for screenshot 1 (exact TRUE_AFFINE fit).
    for name, px, py in (("SAN JUAN", 100, 200), ("PONCE", 900, 1800)):
        lat, lon = apply_affine(TRUE_AFFINE, px, py)
        conn.execute(
            "INSERT INTO geo_anchors (screenshot_id, anchor_kind, name, pixel_x, pixel_y,"
            " lat, lon, observed_at) VALUES (1, 'derived', ?, ?, ?, ?, ?, '2026-06-01T00:00:00Z')",
            (name, px, py, lat, lon),
        )
    # Observed registration + FAA registry row for screenshot 1.
    conn.execute(
        "INSERT INTO aircraft_observations (screenshot_id, registration, identity_status,"
        " source_zone, observed_at)"
        " VALUES (1, 'N407PR', 'confirmed', 'aircraft_card', '2026-06-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO aircraft_registry (n_number, name, manufacturer, model, fetched_at)"
        " VALUES ('N407PR', 'POLICE DEPT PUERTO RICO', 'BELL', '407', '2026-06-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()
    return db


def _vision_csv(path: Path, rows: list[dict]) -> Path:
    fieldnames = [
        "id", "at", "label", "ref_id", "site_id",
        "callsign", "aircraft_type", "operator", "registration",
        "origin_code", "destination_code", "altitude_ft", "ground_speed_mph",
        "flight_status", "image_path", "month_dir",
    ]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return path


VISION_ROWS = [
    {
        "id": "fr24-2026-03-24 09-40-01",
        "at": "2026-03-24T09:40:01",
        "callsign": "N407PR",
        "aircraft_type": "Bell 407",
        "operator": "Police Dept",
        "registration": "N407PR",
        "origin_code": "SJU",
        "altitude_ft": "1200",
        "flight_status": "En Route",
        "image_path": "/Users/op/FR24 Logs/2026-03/2026-03-24 09-40-01.HEIC",
        "month_dir": "2026-03",
    },
    {
        # duplicate basename, resolved by month_dir
        "id": "fr24-dup",
        "at": "2026-05-01T09:00:00",
        "callsign": "N123AB",
        "registration": "N123AB",
        "image_path": "/Users/op/FR24 Logs/2026-05/dup.HEIC",
        "month_dir": "2026-05",
    },
    {
        # no matching screenshot in the store
        "id": "fr24-missing",
        "at": "2026-05-02T09:00:00",
        "callsign": "N999ZZ",
        "image_path": "/Users/op/FR24 Logs/2026-05/missing.HEIC",
        "month_dir": "2026-05",
    },
]


def test_vision_ingest_writes_ocr_and_aircraft_rows(rlsm_db, tmp_path):
    csv_path = _vision_csv(tmp_path / "vision.csv", VISION_ROWS)
    proc = _run([sys.executable, str(INGESTER), "--csv", str(csv_path),
                 "--rlsm-db", str(rlsm_db)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads(proc.stdout)
    assert summary["ocr_rows_inserted"] == 2
    assert summary["aircraft_rows_inserted"] == 2
    assert summary["skipped_unmatched_image"] == 1

    conn = sqlite3.connect(str(rlsm_db))
    ocr = conn.execute(
        "SELECT screenshot_id, zone, engine, raw_text FROM ocr_observations"
        " WHERE engine = 'claude_vision' ORDER BY screenshot_id"
    ).fetchall()
    assert [(r[0], r[1], r[2]) for r in ocr] == [
        (1, "vision_full_frame", "claude_vision"),
        (3, "vision_full_frame", "claude_vision"),
    ]
    payload = json.loads(ocr[0][3])
    assert payload["registration"] == "N407PR"
    assert payload["origin_code"] == "SJU"
    aircraft = conn.execute(
        "SELECT screenshot_id, registration, source_zone, identity_status"
        " FROM aircraft_observations WHERE source_zone = 'vision_full_frame'"
        " ORDER BY screenshot_id"
    ).fetchall()
    assert aircraft == [
        (1, "N407PR", "vision_full_frame", "recovered"),
        (3, "N123AB", "vision_full_frame", "recovered"),
    ]
    runs = conn.execute(
        "SELECT status FROM processing_runs WHERE run_kind = 'vision_csv_ingest'"
    ).fetchall()
    conn.close()
    assert runs == [("completed",)]


def test_vision_ingest_is_idempotent(rlsm_db, tmp_path):
    csv_path = _vision_csv(tmp_path / "vision.csv", VISION_ROWS)
    first = _run([sys.executable, str(INGESTER), "--csv", str(csv_path),
                  "--rlsm-db", str(rlsm_db)])
    second = _run([sys.executable, str(INGESTER), "--csv", str(csv_path),
                   "--rlsm-db", str(rlsm_db)])
    assert json.loads(first.stdout)["ocr_rows_inserted"] == 2
    assert json.loads(second.stdout)["ocr_rows_inserted"] == 0
    assert json.loads(second.stdout)["skipped_already_ingested"] == 2

    conn = sqlite3.connect(str(rlsm_db))
    n = conn.execute(
        "SELECT COUNT(*) FROM ocr_observations WHERE engine = 'claude_vision'"
    ).fetchone()[0]
    conn.close()
    assert n == 2


def test_vision_ingest_dry_run_writes_nothing(rlsm_db, tmp_path):
    csv_path = _vision_csv(tmp_path / "vision.csv", VISION_ROWS)
    proc = _run([sys.executable, str(INGESTER), "--csv", str(csv_path),
                 "--rlsm-db", str(rlsm_db), "--dry-run"])
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["ocr_rows_inserted"] == 2
    conn = sqlite3.connect(str(rlsm_db))
    n = conn.execute("SELECT COUNT(*) FROM ocr_observations").fetchone()[0]
    runs = conn.execute("SELECT COUNT(*) FROM processing_runs").fetchone()[0]
    conn.close()
    assert n == 0 and runs == 0


# ──────────────────────────────────────────────────────────────────────────
# build_producer_package --rlsm-db enrichment
# ──────────────────────────────────────────────────────────────────────────

def _make_operational_db(path: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE screenshots (
            screenshot_id TEXT PRIMARY KEY,
            image_path TEXT,
            flight_id TEXT,
            processed_at TEXT,
            callsign TEXT,
            altitude_ft INTEGER,
            ground_speed_mph INTEGER,
            latitude REAL,
            longitude REAL,
            timestamp TEXT,
            raw_text TEXT,
            ocr_confidence REAL,
            sha256 TEXT,
            coordinate_method TEXT,
            coordinate_confidence REAL,
            estimated_error_m REAL,
            review_status TEXT DEFAULT 'pending'
        )
        """
    )
    for row in rows:
        keys = sorted(row)
        conn.execute(
            f"INSERT INTO screenshots ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
            [row[k] for k in keys],
        )
    conn.commit()
    conn.close()


def _operational_rows() -> list[dict]:
    fixed = GeoCalibration(mode="fixed_pr_bounds").pixel_to_coord(500, 1000, 1170, 2532)
    return [
        {
            "screenshot_id": "op-0001",
            "image_path": "fixtures/op-0001.png",
            "sha256": "a" * 64,  # RLSM screenshot 1: anchors + registry identity
            "callsign": "N407PR",
            "latitude": fixed.lat,
            "longitude": fixed.lon,
            "timestamp": "2026-06-01T11:58:00Z",
            "ocr_confidence": 0.9,
            "coordinate_method": "fixed_pr_bounds",
            "coordinate_confidence": 0.65,
            "review_status": "approved",
        },
        {
            "screenshot_id": "op-0002",
            "image_path": "fixtures/op-0002.png",
            "sha256": "b" * 64,  # RLSM screenshot 2: no anchors, no identity
            "latitude": 18.2,
            "longitude": -66.5,
            "timestamp": "2026-06-01T12:10:00Z",
            "ocr_confidence": 0.5,
            "coordinate_method": "fixed_pr_bounds",
            "coordinate_confidence": 0.65,
        },
    ]


def test_rlsm_enrichment_lifts_calibration_and_adds_registry(rlsm_db, tmp_path):
    op_db = tmp_path / "fr24.db"
    _make_operational_db(op_db, _operational_rows())
    out = tmp_path / "pkg"
    proc = _run([
        sys.executable, str(BUILDER), "--db", str(op_db), "--out", str(out),
        "--mode", "test", "--mark-synthetic", "--rlsm-db", str(rlsm_db),
    ])
    assert proc.returncode == 0, proc.stdout + proc.stderr

    features = json.loads((out / "observations.geojson").read_text())["features"]
    by_id = {f["properties"]["observation_id"]: f["properties"] for f in features}

    enriched = by_id["fr24-op-0001"]
    assert enriched["geometry_status"] == "located"
    assert "FAA registry N407PR: POLICE DEPT PUERTO RICO (BELL 407)" in (
        enriched["description_summary"]
    )
    want_lat, want_lon = apply_affine(TRUE_AFFINE, 500, 1000)
    assert enriched["lat"] == pytest.approx(want_lat, abs=1e-3)
    assert enriched["lon"] == pytest.approx(want_lon, abs=1e-3)

    plain = by_id["fr24-op-0002"]
    assert plain["geometry_status"] == "approximate"
    assert "FAA registry" not in plain["description_summary"]

    lineage = {r["observation_id"]: r for r in json.loads((out / "lineage.json").read_text())}
    assert lineage["fr24-op-0001"]["coordinate_method"] == "per_screenshot_affine"
    assert lineage["fr24-op-0002"]["coordinate_method"] == "fixed_pr_bounds"


def test_builder_without_rlsm_flag_is_unchanged(rlsm_db, tmp_path):
    op_db = tmp_path / "fr24.db"
    _make_operational_db(op_db, _operational_rows())
    out = tmp_path / "pkg_plain"
    proc = _run([
        sys.executable, str(BUILDER), "--db", str(op_db), "--out", str(out),
        "--mode", "test", "--mark-synthetic",
    ])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    features = json.loads((out / "observations.geojson").read_text())["features"]
    for feature in features:
        props = feature["properties"]
        assert props["geometry_status"] == "approximate"
        assert "FAA registry" not in props["description_summary"]
