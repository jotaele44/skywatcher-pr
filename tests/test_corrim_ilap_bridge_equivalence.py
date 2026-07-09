"""Equivalence test for the CORRIM consolidation: ilap_airspace_bridge.py is
now a backward-compat shim over skywatcher.corrim.ilap_airspace_bridge, which
in turn imports gis_intelligence from its new skywatcher.corrim location. See
docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""

import sqlite3

from ilap_airspace_bridge import ILAPAirspaceBridge as OldBridge
from skywatcher.corrim.ilap_airspace_bridge import ILAPAirspaceBridge as NewBridge


def _fixture_db(path: str) -> None:
    conn = sqlite3.connect(path)
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
    for i in range(12):
        conn.execute(
            "INSERT INTO track_points (flight_id, timestamp, latitude, longitude, "
            "altitude_ft, ground_speed_mph) VALUES (?, ?, ?, ?, ?, ?)",
            ("FLT_A", f"2024-03-15T08:{i:02d}:00", 18.44 + i * 0.001,
             -66.0 + i * 0.001, 3000, 100),
        )
    conn.commit()
    conn.close()


def test_shim_reexports_identical_class():
    assert OldBridge is NewBridge


def test_shim_functional_equivalence(tmp_path):
    db = str(tmp_path / "ilap_test.db")
    _fixture_db(db)

    old_out = tmp_path / "old"
    new_out = tmp_path / "new"
    old_out.mkdir()
    new_out.mkdir()

    old_result = OldBridge(db, str(old_out)).export_all()
    new_result = NewBridge(db, str(new_out)).export_all()

    assert set(old_result.keys()) == set(new_result.keys())
    for fname in ("airspace_poi_candidates.geojson",
                  "airspace_ilap_candidates.geojson",
                  "airspace_corridor_candidates.geojson"):
        assert (old_out / fname).read_text() == (new_out / fname).read_text()
