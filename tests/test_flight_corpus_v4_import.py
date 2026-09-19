import json
from pathlib import Path

ROOT=Path(__file__).parents[1]
SCHEMA=ROOT/"schemas"/"flight_corpus_v4_import.schema.json"
README=ROOT/"data"/"flight_tracks"/"corpus_v4"/"README.md"
VALIDATOR=ROOT/"scripts"/"validate_flight_corpus_v4_import.py"

def test_import_assets_exist():
    assert SCHEMA.is_file() and README.is_file() and VALIDATOR.is_file()

def test_schema_fixes_v4_denominators():
    s=json.loads(SCHEMA.read_text())
    d=s["properties"]["denominators"]["properties"]
    assert d["nonempty_logical_records"]["const"]==696
    assert d["single_point_exclusions"]["const"]==11
    assert d["trajectory_eligible"]["const"]==685
    assert d["unordered_pair_denominator"]["const"]==234270

def test_no_mission_role_exists():
    s=json.loads(SCHEMA.read_text())
    roles=s["properties"]["datasets"]["items"]["properties"]["role"]["enum"]
    assert "MISSION" not in roles
    assert "RAW_LINEAGE_GEOMETRY" in roles

def test_readme_forbids_placeholder_identity():
    t=README.read_text()
    assert "No placeholder hash is canonical" in t
    assert "monolithic source/evidence ZIP is intentionally not committed" in t
