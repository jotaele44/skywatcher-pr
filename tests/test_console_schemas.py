import copy
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
NEW_SCHEMA_NAMES = {
    "source_taxonomy.schema.json",
    "aircraft_state.schema.json",
    "track_point.schema.json",
    "flight_session.schema.json",
    "airport_operational_state.schema.json",
    "ui_preferences.schema.json",
    "bookmark.schema.json",
}


def load(name):
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def test_all_seven_phase1_schemas_are_valid_draft_2020_12():
    assert {path.name for path in SCHEMAS.glob("*.json")}.issuperset(NEW_SCHEMA_NAMES)
    for name in sorted(NEW_SCHEMA_NAMES):
        jsonschema.Draft202012Validator.check_schema(load(name))


def test_aircraft_state_requires_provenance_and_synthetic_separation():
    schema = load("aircraft_state.schema.json")
    resolved_schema = copy.deepcopy(schema)
    resolved_schema["properties"]["provenance"] = load("source_taxonomy.schema.json")
    validator = jsonschema.Draft202012Validator(resolved_schema)
    valid = {
        "schema_version": "0.1.0",
        "state_id": "state-1",
        "aircraft_id": "ac-1",
        "observed_at_utc": "2026-07-20T16:00:00Z",
        "lat": 18.4,
        "lon": -66.0,
        "on_ground": False,
        "position_status": "measured",
        "provenance": {
            "source_family": "synthetic_test",
            "source_provider": "fixture",
            "source_method": "adsb",
            "data_rights": "synthetic",
            "operational_mode": "batch",
            "source_record_id": "src-1",
            "lineage_id": "lin-1",
            "artifact_path": "fixture://aircraft-state",
            "artifact_sha256": None,
            "ingest_adapter": "test-fixture"
        },
        "synthetic": True
    }
    validator.validate(valid)

    invalid = dict(valid)
    invalid.pop("provenance")
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(invalid)
