"""Regression guard for requirement 8 (no intent/purpose inference anywhere in
the pipeline): FlightMissionAnalyzer/_deduce_mission/MissionAnalysis must not
be part of skywatcher.fpim's active public surface, and no core/satim/fpim/
corrim module may import skywatcher.legacy. See
docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""

import ast
from pathlib import Path

import skywatcher.fpim as fpim_package
import skywatcher.fpim.aircraft_profile as aircraft_profile

REPO_ROOT = Path(__file__).resolve().parents[1]

QUARANTINED_NAMES = {"FlightMissionAnalyzer", "MissionAnalysis", "analyze_all_aircraft", "_deduce_mission"}

ACTIVE_BUCKET_DIRS = [
    REPO_ROOT / "src" / "skywatcher" / "core",
    REPO_ROOT / "src" / "skywatcher" / "fpim",
    REPO_ROOT / "src" / "skywatcher" / "corrim",
    REPO_ROOT / "src" / "skywatcher" / "correlation",
    REPO_ROOT / "src" / "skywatcher" / "fusion",
]


def test_fpim_package_surface_excludes_quarantined_names():
    assert not (QUARANTINED_NAMES & set(dir(fpim_package)))
    assert not (QUARANTINED_NAMES & set(dir(aircraft_profile)))


def test_no_active_bucket_imports_legacy():
    violations = []
    for directory in ACTIVE_BUCKET_DIRS:
        for py_file in directory.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("skywatcher.legacy"):
                    violations.append(f"{py_file}: imports {node.module}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("skywatcher.legacy"):
                            violations.append(f"{py_file}: imports {alias.name}")
    assert not violations, "\n".join(violations)


def test_root_compatibility_surface_excludes_quarantined_names():
    import aircraft_intelligence as facade

    assert not (QUARANTINED_NAMES & set(facade.__all__))


def test_unknown_aircraft_role_remains_unknown(tmp_path):
    import sqlite3

    db_path = tmp_path / "flights.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE flights (callsign TEXT, aircraft_type TEXT, operator TEXT, takeoff_time TEXT)"
    )
    conn.execute(
        "INSERT INTO flights VALUES (?, ?, ?, ?)",
        ("NTEST1", "C172", "Example operator", "2026-07-27T12:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    profile = aircraft_profile.AircraftIntelligence(str(db_path)).lookup_aircraft("NTEST1")
    assert profile.aircraft_type == "C172"
    assert profile.operator == "Example operator"
    assert profile.primary_mission == "Unknown"
