"""Tests for PRIntelAdapter: 10 files created, gate status."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from integration.pr_intel_adapter import PROVENANCE_COLS, PRIntelAdapter


def test_export_all_creates_required_files(populated_db, tmp_output):
    adapter = PRIntelAdapter(populated_db, str(tmp_output))
    report = adapter.export_all()

    for fname in PRIntelAdapter.REQUIRED_OUTPUTS:
        assert (tmp_output / fname).exists(), f"Missing: {fname}"


def test_integration_report_has_all_gates(populated_db, tmp_output):
    adapter = PRIntelAdapter(populated_db, str(tmp_output))
    report = adapter.export_all()

    expected_gates = {
        "schema_validation",
        "coordinate_coverage",
        "ocr_confidence_gate",
        "evidence_chain_coverage",
        "export_completeness",
        "temporal_integrity",
    }
    assert set(report["gates"].keys()) == expected_gates


def test_integration_report_overall_status_present(populated_db, tmp_output):
    adapter = PRIntelAdapter(populated_db, str(tmp_output))
    report = adapter.export_all()
    assert report["overall_status"] in ("PASS", "FAIL")


def test_integration_report_gate_status_values(populated_db, tmp_output):
    adapter = PRIntelAdapter(populated_db, str(tmp_output))
    report = adapter.export_all()
    for gate_name, gate in report["gates"].items():
        assert gate["status"] in ("PASS", "FAIL"), f"Gate {gate_name}: invalid status"


def test_source_manifest_valid_json(populated_db, tmp_output):
    PRIntelAdapter(populated_db, str(tmp_output)).export_all()
    manifest = json.loads((tmp_output / "source_manifest.json").read_text())
    assert "generated_at" in manifest
    assert "files" in manifest
    assert isinstance(manifest["files"], list)


def test_gis_features_epsg4326(populated_db, tmp_output):
    PRIntelAdapter(populated_db, str(tmp_output)).export_all()
    data = json.loads((tmp_output / "gis_airspace_features.geojson").read_text())
    crs_name = data.get("crs", {}).get("properties", {}).get("name", "")
    assert "4326" in crs_name


def test_route_lines_epsg4326(populated_db, tmp_output):
    PRIntelAdapter(populated_db, str(tmp_output)).export_all()
    data = json.loads((tmp_output / "route_lines.geojson").read_text())
    crs_name = data.get("crs", {}).get("properties", {}).get("name", "")
    assert "4326" in crs_name


def test_gis_features_carry_meta_block(populated_db, tmp_output):
    """T5-41: every GeoJSON Feature must carry a standardized _meta block."""
    PRIntelAdapter(populated_db, str(tmp_output)).export_all()
    data = json.loads((tmp_output / "gis_airspace_features.geojson").read_text())
    for feat in data["features"]:
        meta = feat["properties"].get("_meta")
        assert meta is not None, "missing _meta block"
        assert meta["producer_module"] == "integration.pr_intel_adapter"
        assert meta["source_artifact"] == "gis_airspace_features.geojson"
        assert meta["produced_at"], "produced_at must be non-empty"


def test_route_lines_carry_meta_block(populated_db, tmp_output):
    """T5-41: route_lines.geojson Features carry the _meta block."""
    PRIntelAdapter(populated_db, str(tmp_output)).export_all()
    data = json.loads((tmp_output / "route_lines.geojson").read_text())
    for feat in data["features"]:
        meta = feat["properties"].get("_meta")
        assert meta is not None
        assert meta["producer_module"] == "integration.pr_intel_adapter"
        assert meta["source_artifact"] == "route_lines.geojson"


def test_export_completeness_gate_passes(populated_db, tmp_output):
    adapter = PRIntelAdapter(populated_db, str(tmp_output))
    report = adapter.export_all()
    gate = report["gates"]["export_completeness"]
    assert gate["status"] == "PASS", f"Missing files: {gate.get('missing')}"


def test_integration_report_written_to_disk(populated_db, tmp_output):
    PRIntelAdapter(populated_db, str(tmp_output)).export_all()
    report_path = tmp_output / "integration_report.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text())
    assert "overall_status" in data
    assert "gates" in data


def test_export_idempotent(populated_db, tmp_output):
    adapter = PRIntelAdapter(populated_db, str(tmp_output))
    report1 = adapter.export_all()
    report2 = adapter.export_all()
    assert report1["overall_status"] == report2["overall_status"]


# ── Stage 1 hardening tests ───────────────────────────────────────────────────

def _create_minimal_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS flights (
            flight_id TEXT PRIMARY KEY, callsign TEXT,
            aircraft_type TEXT, operator TEXT,
            origin_airport TEXT, destination_airport TEXT,
            origin_lat REAL, origin_lon REAL,
            dest_lat REAL, dest_lon REAL,
            takeoff_time TEXT, landing_time TEXT,
            flight_duration_minutes INTEGER, max_altitude_ft INTEGER,
            avg_speed_mph REAL, mission_type TEXT, num_screenshots INTEGER
        );
        CREATE TABLE IF NOT EXISTS screenshots (
            screenshot_id TEXT PRIMARY KEY, image_path TEXT,
            flight_id TEXT, processed_at TEXT, callsign TEXT,
            altitude_ft INTEGER, ground_speed_mph INTEGER,
            latitude REAL, longitude REAL, timestamp TEXT,
            raw_text TEXT, ocr_confidence REAL, sha256 TEXT,
            coordinate_method TEXT, coordinate_confidence REAL,
            estimated_error_m REAL, review_status TEXT DEFAULT 'pending'
        );
        CREATE TABLE IF NOT EXISTS track_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT, flight_id TEXT,
            timestamp TEXT, latitude REAL, longitude REAL,
            altitude_ft INTEGER, ground_speed_mph INTEGER
        );
        CREATE TABLE IF NOT EXISTS alerts (
            alert_id TEXT PRIMARY KEY, flight_id TEXT, callsign TEXT,
            category TEXT, severity TEXT, title TEXT, description TEXT,
            evidence TEXT, timestamp TEXT, recommended_action TEXT,
            auto_resolved INTEGER DEFAULT 0, acknowledged INTEGER DEFAULT 0,
            acknowledged_at TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS mission_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT, flight_id TEXT,
            mission_type TEXT, total_score REAL, confidence_level REAL,
            signal_scores TEXT, explanation TEXT, scored_at TEXT
        );
        CREATE TABLE IF NOT EXISTS aircraft_profiles (
            callsign TEXT PRIMARY KEY, aircraft_type TEXT,
            owner TEXT, operator TEXT, primary_mission TEXT,
            confidence_level REAL, total_flights INTEGER,
            first_seen TEXT, last_seen TEXT, operational_patterns TEXT
        );
        CREATE TABLE IF NOT EXISTS extraction_confidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT, screenshot_id TEXT,
            field_name TEXT, value TEXT, ocr_confidence REAL,
            validation_score REAL, consistency_score REAL,
            extraction_method TEXT, source_frame TEXT
        );
    """)


def _make_empty_db(tmp_path: Path) -> str:
    db = str(tmp_path / "empty.db")
    conn = sqlite3.connect(db)
    _create_minimal_schema(conn)
    conn.commit()
    conn.close()
    return db


def _make_no_coords_db(tmp_path: Path) -> str:
    db = str(tmp_path / "no_coords.db")
    conn = sqlite3.connect(db)
    _create_minimal_schema(conn)
    conn.execute(
        "INSERT INTO flights VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("FLT_001", "N1234", "H125", "PREPA", "SJU", "PSE",
         None, None, None, None,
         "2024-03-15T08:00:00", "2024-03-15T09:00:00",
         60, 3000, 100.0, "SURVEY", 0),
    )
    conn.commit()
    conn.close()
    return db


def _make_low_ocr_db(tmp_path: Path) -> str:
    db = str(tmp_path / "low_ocr.db")
    conn = sqlite3.connect(db)
    _create_minimal_schema(conn)
    conn.execute(
        "INSERT INTO flights VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("FLT_001", "N1234", "H125", "PREPA", "SJU", "PSE",
         18.44, -66.0, 18.0, -66.5,
         "2024-03-15T08:00:00", "2024-03-15T09:00:00",
         60, 3000, 100.0, "SURVEY", 1),
    )
    conn.execute(
        "INSERT INTO screenshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("SS_001", "/tmp/img.jpg", "FLT_001", "2024-03-15T08:00:00",
         "N1234", 3000, 100, 18.44, -66.0, "2024-03-15T08:00:00",
         "OCR text", 0.1, None, "fixed_pr_bounds", 0.65, 1500.0, "pending"),
    )
    conn.commit()
    conn.close()
    return db


def test_export_all_empty_db_overall_status_pass(tmp_path):
    # All gate skip-when-empty conditions fire → PASS.
    # TODO: a future stage should distinguish NO_DATA from genuine PASS so that
    #       an empty DB export cannot satisfy a readiness gate.
    db = _make_empty_db(tmp_path)
    report = PRIntelAdapter(db, str(tmp_path / "out")).export_all()
    assert report["overall_status"] == "PASS"


def test_coordinate_coverage_gate_fails_when_no_coords(tmp_path):
    db = _make_no_coords_db(tmp_path)
    report = PRIntelAdapter(db, str(tmp_path / "out")).export_all()
    gate = report["gates"]["coordinate_coverage"]
    assert gate["status"] == "FAIL"
    assert gate["pct_with_coords"] < gate["threshold"]


def test_ocr_confidence_gate_fails_when_avg_below_threshold(tmp_path):
    db = _make_low_ocr_db(tmp_path)
    report = PRIntelAdapter(db, str(tmp_path / "out")).export_all()
    gate = report["gates"]["ocr_confidence_gate"]
    assert gate["status"] == "FAIL"
    assert gate["avg_confidence"] < gate["threshold"]


def test_airspace_events_parquet_has_provenance_columns(populated_db, tmp_output):
    PRIntelAdapter(populated_db, str(tmp_output)).export_all()
    table = pq.read_table(str(tmp_output / "airspace_events.parquet"))
    col_names = table.schema.names
    expected = [col for col, _ in PROVENANCE_COLS]
    for col in expected:
        assert col in col_names, f"Provenance column missing from parquet: {col}"


def test_export_pr_intel_cli_exits_nonzero_if_db_missing(tmp_path):
    result = subprocess.run(
        [sys.executable, "run_all.py",
         "--export-pr-intel", str(tmp_path / "out"),
         "--db", str(tmp_path / "nonexistent.db")],
        capture_output=True, text=True,
        cwd=str(Path(__file__).parent.parent),
    )
    assert result.returncode != 0, "CLI should exit nonzero when DB is missing"


def test_integration_report_coordinate_coverage_pct_gt_zero(populated_db, tmp_output):
    report = PRIntelAdapter(populated_db, str(tmp_output)).export_all()
    pct = report["gates"]["coordinate_coverage"]["pct_with_coords"]
    assert pct > 0.0, "Fixture flights all have coords — pct should be > 0"
