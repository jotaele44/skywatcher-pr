"""Tests for ILAP Airspace Bridge — Task 21."""

import pytest

from ilap_airspace_bridge import (
    CONFIDENCE_WEIGHTS,
    ILAPAirspaceBridge,
    _infra_align_score,
)


def test_confidence_weights_sum_to_one():
    total = sum(CONFIDENCE_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9, f"CONFIDENCE_WEIGHTS sum = {total}, expected 1.0"


def test_infra_align_score_near_sju_above_baseline():
    # SJU (Luis Muñoz Marín International Airport) is at approximately 18.44, -66.0.
    # A track centroid at that location should align well with known PR infrastructure
    # and return a score above the placeholder baseline of 0.3.
    score = _infra_align_score(18.44, -66.0)
    assert 0.0 <= score <= 1.0, f"Score {score} out of [0, 1]"
    assert score > 0.3, f"Score {score} not above 0.3 baseline for near-SJU track"


def test_infra_align_score_far_ocean_low():
    # A point far from any PR infrastructure (mid-Atlantic) should score low.
    score = _infra_align_score(25.0, -45.0)
    assert 0.0 <= score <= 1.0
    assert score < 0.5, f"Score {score} unexpectedly high for mid-ocean point"


def test_ilap_bridge_corridor_candidate_output_shape(tmp_path):
    import sqlite3
    db = str(tmp_path / "ilap_test.db")
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS track_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT, flight_id TEXT,
            timestamp TEXT, latitude REAL, longitude REAL,
            altitude_ft INTEGER, ground_speed_mph INTEGER
        );
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
    """)
    # Insert track points that cluster around SJU — should produce at least one POI
    for i in range(12):
        conn.execute(
            "INSERT INTO track_points (flight_id, timestamp, latitude, longitude, "
            "altitude_ft, ground_speed_mph) VALUES (?, ?, ?, ?, ?, ?)",
            (f"FLT_A", f"2024-03-15T08:{i:02d}:00", 18.44 + i * 0.001,
             -66.0 + i * 0.001, 3000, 100),
        )
        conn.execute(
            "INSERT INTO track_points (flight_id, timestamp, latitude, longitude, "
            "altitude_ft, ground_speed_mph) VALUES (?, ?, ?, ?, ?, ?)",
            (f"FLT_B", f"2024-03-15T09:{i:02d}:00", 18.44 + i * 0.001,
             -66.0 + i * 0.001, 3000, 100),
        )
    conn.commit()
    conn.close()

    bridge = ILAPAirspaceBridge(db, str(tmp_path))
    result = bridge.export_all()

    assert isinstance(result, dict), "export_all must return a dict"
    assert "generated_at" in result
    # Verify each GeoJSON output file was created
    for fname in ("airspace_poi_candidates.geojson",
                  "airspace_ilap_candidates.geojson",
                  "airspace_corridor_candidates.geojson"):
        assert (tmp_path / fname).exists(), f"Missing output: {fname}"
