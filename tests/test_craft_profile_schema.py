"""craft_profile.schema.json is a valid draft-07 schema and accepts built profiles."""

import json
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "schemas" / "craft_profile.schema.json"


@pytest.fixture(scope="module")
def schema():
    return json.loads(SCHEMA.read_text())


def test_schema_is_valid_draft7(schema):
    jsonschema.Draft7Validator.check_schema(schema)


def test_minimal_profile_validates(schema):
    minimal = {
        "registration": "N5854Z",
        "data_source": "known_db",
        "confidence_level": 0.95,
        "profile_confidence_grade": "VERIFIED",
        "generated_at": "2026-07-30T00:00:00",
        "source_baseline": "rlsm@max_ts=2025-06-05T08:30:00",
    }
    jsonschema.validate(minimal, schema)


def test_bad_grade_rejected(schema):
    bad = {
        "registration": "N5854Z",
        "data_source": "known_db",
        "confidence_level": 0.95,
        "profile_confidence_grade": "SUPER_SURE",  # not in enum
        "generated_at": "2026-07-30T00:00:00",
        "source_baseline": "x",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
