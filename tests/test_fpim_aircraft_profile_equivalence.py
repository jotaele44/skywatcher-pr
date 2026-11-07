import sqlite3

"""FPIM aircraft-profile compatibility and no-mission-inference gates."""

from aircraft_intelligence import AircraftIntelligence as OldIntel
from aircraft_intelligence import AircraftProfile as OldProfile
from skywatcher.fpim.aircraft_profile import AircraftIntelligence as NewIntel
from skywatcher.fpim.aircraft_profile import AircraftProfile as NewProfile


def test_shim_reexports_identical_classes():
    assert OldIntel is NewIntel
    assert OldProfile is NewProfile


def test_shim_functional_equivalence():
    old_profile = OldIntel("/nonexistent.db").lookup_aircraft("N5854Z")
    new_profile = NewIntel("/nonexistent.db").lookup_aircraft("N5854Z")
    assert old_profile == new_profile
    assert old_profile.operator == "PREPA"


def test_unknown_aircraft_type_never_implies_mission(tmp_path):
    db_path = tmp_path / "profile.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE flights (callsign TEXT, aircraft_type TEXT, operator TEXT, takeoff_time TEXT)"
    )
    conn.execute(
        "INSERT INTO flights (callsign, aircraft_type, operator, takeoff_time) VALUES (?, ?, ?, ?)",
        ("N999ZZ", "Airbus H125", "Example Operator", "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    profile = NewIntel(str(db_path)).lookup_aircraft("N999ZZ")
    assert profile.aircraft_type == "Airbus H125"
    assert profile.operator == "Example Operator"
    assert profile.primary_mission == "Unknown"
    assert profile.data_source == "db_history"
    assert profile.confidence_level == 0.20
