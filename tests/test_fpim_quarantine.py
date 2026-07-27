import ast
from pathlib import Path

import skywatcher.fpim as fpim_package
import skywatcher.fpim.aircraft_profile as aircraft_profile

REPO_ROOT = Path(__file__).resolve().parents[1]
QUARANTINED_NAMES = {
    "FlightMissionAnalyzer",
    "MissionAnalysis",
    "analyze_all_aircraft",
    "_deduce_mission",
}
ACTIVE_BUCKET_DIRS = [
    REPO_ROOT / "src" / "skywatcher" / name
    for name in ("core", "fpim", "corrim", "correlation", "fusion")
]


def test_active_surfaces_exclude_quarantined_names():
    assert not (QUARANTINED_NAMES & set(dir(fpim_package)))
    assert not (QUARANTINED_NAMES & set(dir(aircraft_profile)))
    import aircraft_intelligence as facade

    assert not (QUARANTINED_NAMES & set(facade.__all__))


def test_no_active_bucket_imports_legacy():
    violations = []
    for directory in ACTIVE_BUCKET_DIRS:
        for py_file in directory.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("skywatcher.legacy"):
                    violations.append(str(py_file))
                if isinstance(node, ast.Import):
                    violations.extend(
                        str(py_file)
                        for alias in node.names
                        if alias.name.startswith("skywatcher.legacy")
                    )
    assert not violations


def test_unknown_role_and_exact_identifier_matching(tmp_path):
    intelligence = aircraft_profile.AircraftIntelligence(str(tmp_path / "none.sqlite"))
    profile = intelligence.lookup_aircraft("N5854Z")
    assert profile.primary_mission == "Unknown"
    assert profile.secondary_missions == []
    assert profile.operational_patterns == {}
    assert profile.data_source == "unverified_registry"

    partial = intelligence.lookup_aircraft("N5854")
    assert partial.data_source == "observed_history"
    assert intelligence.find_unknown(["N5854", "N5854Z"]) == ["N5854"]
