"""
Shared pytest fixtures for the PR Airspace Intelligence test suite.
"""

import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest


@pytest.fixture
def tmp_output(tmp_path):
    """Temporary directory for test output files."""
    return tmp_path


@pytest.fixture
def populated_db(tmp_path):
    """
    SQLite database pre-populated with:
      - 3 flights (N5854Z/PREPA, C6062/USCG, N767PD/FURA)
      - 5 track_points per flight (within PR bounds)
      - 3 screenshots per flight (with ocr_confidence, coordinate fields)
      - 1 alert per flight
      - 1 mission_score row per flight
    """
    db_path = str(tmp_path / "test_flights.db")
    conn = sqlite3.connect(db_path)
    _create_schema(conn)
    _insert_data(conn)
    conn.commit()
    conn.close()
    return db_path


def _create_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS flights (
            flight_id TEXT PRIMARY KEY,
            callsign TEXT,
            aircraft_type TEXT,
            operator TEXT,
            origin_airport TEXT,
            destination_airport TEXT,
            origin_lat REAL,
            origin_lon REAL,
            dest_lat REAL,
            dest_lon REAL,
            takeoff_time TEXT,
            landing_time TEXT,
            flight_duration_minutes INTEGER,
            max_altitude_ft INTEGER,
            avg_speed_mph REAL,
            mission_type TEXT,
            num_screenshots INTEGER
        );

        CREATE TABLE IF NOT EXISTS track_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_id TEXT,
            timestamp TEXT,
            latitude REAL,
            longitude REAL,
            altitude_ft INTEGER,
            ground_speed_mph INTEGER
        );

        CREATE TABLE IF NOT EXISTS screenshots (
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
        );

        CREATE TABLE IF NOT EXISTS alerts (
            alert_id TEXT PRIMARY KEY,
            flight_id TEXT,
            callsign TEXT,
            category TEXT,
            severity TEXT,
            title TEXT,
            description TEXT,
            evidence TEXT,
            timestamp TEXT,
            recommended_action TEXT,
            auto_resolved INTEGER DEFAULT 0,
            acknowledged INTEGER DEFAULT 0,
            acknowledged_at TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS mission_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_id TEXT,
            mission_type TEXT,
            total_score REAL,
            confidence_level REAL,
            signal_scores TEXT,
            explanation TEXT,
            scored_at TEXT
        );

        CREATE TABLE IF NOT EXISTS aircraft_profiles (
            callsign TEXT PRIMARY KEY,
            aircraft_type TEXT,
            owner TEXT,
            operator TEXT,
            primary_mission TEXT,
            confidence_level REAL,
            total_flights INTEGER,
            first_seen TEXT,
            last_seen TEXT,
            operational_patterns TEXT
        );

        CREATE TABLE IF NOT EXISTS extraction_confidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            screenshot_id TEXT,
            field_name TEXT,
            value TEXT,
            ocr_confidence REAL,
            validation_score REAL,
            consistency_score REAL,
            extraction_method TEXT,
            source_frame TEXT
        );
    """)


FLIGHTS = [
    {
        "flight_id": "FLT_N5854Z_001",
        "callsign": "N5854Z",
        "aircraft_type": "H125",
        "operator": "Puerto Rico Electric Power Authority",
        "origin_airport": "SJU",
        "destination_airport": "PSE",
        "origin_lat": 18.4373,
        "origin_lon": -66.0018,
        "dest_lat": 18.0083,
        "dest_lon": -66.5632,
        "takeoff_time": "2024-03-15T08:00:00",
        "landing_time": "2024-03-15T09:30:00",
        "flight_duration_minutes": 90,
        "max_altitude_ft": 3500,
        "avg_speed_mph": 120.0,
        "mission_type": "INFRASTRUCTURE_SURVEY",
        "num_screenshots": 3,
    },
    {
        "flight_id": "FLT_C6062_001",
        "callsign": "C6062",
        "aircraft_type": "MH-60",
        "operator": "US Coast Guard",
        "origin_airport": "BQN",
        "destination_airport": "SJU",
        "origin_lat": 18.4948,
        "origin_lon": -67.1294,
        "dest_lat": 18.4373,
        "dest_lon": -66.0018,
        "takeoff_time": "2024-03-15T10:00:00",
        "landing_time": "2024-03-15T11:15:00",
        "flight_duration_minutes": 75,
        "max_altitude_ft": 5000,
        "avg_speed_mph": 160.0,
        "mission_type": "MARITIME_PATROL",
        "num_screenshots": 3,
    },
    {
        "flight_id": "FLT_N767PD_001",
        "callsign": "N767PD",
        "aircraft_type": "B407",
        "operator": "Puerto Rico Police FURA",
        "origin_airport": "SIG",
        "destination_airport": "BQN",
        "origin_lat": 18.4561,
        "origin_lon": -66.0978,
        "dest_lat": 18.4948,
        "dest_lon": -67.1294,
        "takeoff_time": "2024-03-15T12:00:00",
        "landing_time": "2024-03-15T13:00:00",
        "flight_duration_minutes": 60,
        "max_altitude_ft": 2500,
        "avg_speed_mph": 100.0,
        "mission_type": "LAW_ENFORCEMENT",
        "num_screenshots": 3,
    },
]


def _insert_data(conn: sqlite3.Connection):
    base_time = datetime(2024, 3, 15, 8, 0, 0)

    for f in FLIGHTS:
        conn.execute(
            "INSERT INTO flights VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f["flight_id"], f["callsign"], f["aircraft_type"], f["operator"],
                f["origin_airport"], f["destination_airport"],
                f["origin_lat"], f["origin_lon"], f["dest_lat"], f["dest_lon"],
                f["takeoff_time"], f["landing_time"], f["flight_duration_minutes"],
                f["max_altitude_ft"], f["avg_speed_mph"], f["mission_type"], f["num_screenshots"],
            ),
        )

        # 5 track points per flight, incrementing lat/lon slightly
        for i in range(5):
            ts = (base_time + timedelta(minutes=i * 15)).isoformat()
            conn.execute(
                "INSERT INTO track_points (flight_id, timestamp, latitude, longitude, altitude_ft, ground_speed_mph) "
                "VALUES (?,?,?,?,?,?)",
                (
                    f["flight_id"], ts,
                    round(f["origin_lat"] + i * 0.01, 5),
                    round(f["origin_lon"] + i * 0.01, 5),
                    f["max_altitude_ft"],
                    int(f["avg_speed_mph"]),
                ),
            )

        # 3 screenshots per flight
        for j in range(3):
            ss_id = f"{f['flight_id']}_SS{j:02d}"
            ts = (base_time + timedelta(minutes=j * 30)).isoformat()
            conn.execute(
                "INSERT INTO screenshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ss_id, f"/tmp/img_{ss_id}.jpg", f["flight_id"],
                    datetime.utcnow().isoformat(),
                    f["callsign"], f["max_altitude_ft"], int(f["avg_speed_mph"]),
                    f["origin_lat"], f["origin_lon"], ts,
                    f"OCR text for {f['callsign']}", 0.85,
                    None, "fixed_pr_bounds", 0.65, 1500.0, "pending",
                ),
            )

        # 1 alert per flight
        alert_id = f"ALERT_{f['flight_id']}"
        conn.execute(
            "INSERT INTO alerts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                alert_id, f["flight_id"], f["callsign"],
                "FLIGHT_PATTERN", "MEDIUM",
                f"Pattern alert for {f['callsign']}",
                "Recurring route detected", "[]",
                base_time.isoformat(), "Monitor",
                0, 0, None, base_time.isoformat(),
            ),
        )

        # 1 mission score per flight
        conn.execute(
            "INSERT INTO mission_scores (flight_id, mission_type, total_score, confidence_level, signal_scores, explanation, scored_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                f["flight_id"], f["mission_type"], 0.75, 0.80,
                '{"speed": 0.8, "altitude": 0.7}',
                f"Mission inference for {f['callsign']}",
                base_time.isoformat(),
            ),
        )

        # Aircraft profile
        conn.execute(
            "INSERT OR REPLACE INTO aircraft_profiles VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                f["callsign"], f["aircraft_type"], f["operator"], f["operator"],
                f["mission_type"], 0.80, 1,
                f["takeoff_time"], f["landing_time"], "[]",
            ),
        )


# ── Task 39: shared pr_fixture_db fixture ────────────────────────────────────

@pytest.fixture
def pr_fixture_db(tmp_path):
    """Minimal in-memory SQLite DB with 5 synthetic flights (Task 39).

    Reusable across test files via conftest.
    """
    import sqlite3, json
    db_path = str(tmp_path / "pr_fixture.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS flights (
            flight_id TEXT PRIMARY KEY, callsign TEXT, aircraft_type TEXT,
            operator TEXT, takeoff_time TEXT, landing_time TEXT,
            origin_lat REAL, origin_lon REAL, dest_lat REAL, dest_lon REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS track_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_id TEXT, lat REAL, lon REAL, altitude_ft INTEGER,
            speed_kts INTEGER, timestamp TEXT
        )
    """)
    synthetic_flights = [
        ("FLT-PR-001", "N5854Z",  "Cessna 172",    "Private",    "2024-03-14T10:00:00Z", "2024-03-14T11:30:00Z", 18.44, -66.00, 18.25, -65.90),
        ("FLT-PR-002", "N767PD",  "Bell 407",      "PR Police",  "2024-03-14T08:00:00Z", "2024-03-14T09:00:00Z", 18.50, -67.10, 18.48, -67.05),
        ("FLT-PR-003", "N684JB",  "Beech King Air","Charter",    "2024-03-14T14:00:00Z", "2024-03-14T15:00:00Z", 18.43, -66.00, 17.99, -66.56),
        ("FLT-PR-004", "N911PR",  "H145",          "EMS",        "2024-03-14T12:00:00Z", "2024-03-14T12:45:00Z", 18.44, -66.07, 18.40, -66.02),
        ("FLT-PR-005", "C6062",   "Unknown",       "Unknown",    "2024-03-14T22:00:00Z", "2024-03-14T23:30:00Z", 18.30, -65.80, 18.45, -65.70),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO flights VALUES (?,?,?,?,?,?,?,?,?,?)",
        synthetic_flights,
    )
    conn.commit()
    conn.close()
    return db_path


# ── Task 3: CONFIDENCE_WEIGHTS integrity assertion ────────────────────────────

def test_confidence_weights_sum_to_one():
    """CONFIDENCE_WEIGHTS in ilap_airspace_bridge must sum to exactly 1.0 (Task 3)."""
    from ilap_airspace_bridge import CONFIDENCE_WEIGHTS
    total = sum(CONFIDENCE_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9, (
        f"CONFIDENCE_WEIGHTS sum to {total}, expected 1.0. Weights: {CONFIDENCE_WEIGHTS}"
    )
