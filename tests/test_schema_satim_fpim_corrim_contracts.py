"""Round-trip validation for the new SATIM/FPIM/CORRIM output-contract
schemas (requirement 5: shared schemas). No jsonschema dependency exists in
this repo (confirmed absent from pyproject.toml everywhere) and existing
validation (scripts/validate_airspace_export.py) is hand-rolled, so this test
uses the same lightweight, stdlib-only structural checker rather than
introducing a new dependency."""

import json
from pathlib import Path

SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _validate(instance, schema, path="$") -> list[str]:
    errors: list[str] = []

    if "const" in schema:
        if instance != schema["const"]:
            errors.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")
        return errors

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")

    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(instance, dict):
            errors.append(f"{path}: expected object, got {type(instance).__name__}")
            return errors
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required field {key!r}")
        if schema.get("additionalProperties") is False:
            allowed = set(schema.get("properties", {}))
            for key in instance:
                if key not in allowed:
                    errors.append(f"{path}: unexpected field {key!r}")
        for key, subschema in schema.get("properties", {}).items():
            if key in instance:
                errors.extend(_validate(instance[key], subschema, f"{path}.{key}"))
    elif schema_type == "array":
        if not isinstance(instance, list):
            errors.append(f"{path}: expected array, got {type(instance).__name__}")
            return errors
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: expected at least {schema['minItems']} items, got {len(instance)}")
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(instance):
                errors.extend(_validate(item, item_schema, f"{path}[{i}]"))
    elif schema_type in ("number", "integer"):
        if not isinstance(instance, (int, float)) or isinstance(instance, bool):
            errors.append(f"{path}: expected {schema_type}, got {type(instance).__name__}")
        else:
            if "minimum" in schema and instance < schema["minimum"]:
                errors.append(f"{path}: {instance} below minimum {schema['minimum']}")
            if "maximum" in schema and instance > schema["maximum"]:
                errors.append(f"{path}: {instance} above maximum {schema['maximum']}")
    elif schema_type == "string":
        if not isinstance(instance, str):
            errors.append(f"{path}: expected string, got {type(instance).__name__}")
        elif "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: string shorter than minLength {schema['minLength']}")

    return errors


def test_satim_output_contract_minimal_document():
    schema = _load_schema("satim_output_contract.schema.json")
    doc = {
        "satim_output_id": "satim-1",
        "signal_domain": "terrain_imagery",
        "observation_type": "tile_seam",
        "lat": 18.40,
        "lon": -66.10,
        "evidence_tier": "T2",
        "confidence": 0.7,
        "geometry_status": "located",
        "source_layer": "L5_synthetic_boundary_classifier",
    }
    assert _validate(doc, schema) == []


def test_fpim_output_contract_with_pois_along_path():
    schema = _load_schema("fpim_output_contract.schema.json")
    doc = {
        "fpim_output_id": "fpim-1",
        "flight_id": "FLT-001",
        "label_independent": True,
        "behavior_tags": ["loiter"],
        "pois_along_path": [
            {
                "footprint_id": "fp-1",
                "facility_name": "Test Helipad",
                "facility_type": "helipad",
                "distance_m": 500.0,
                "radius_m": 2000,
                "match_type": "near_ground_aviation_node",
                "score": 0.8,
            }
        ],
        "evidence_tier": "T2",
        "confidence": 0.6,
    }
    assert _validate(doc, schema) == []


def test_fpim_output_contract_empty_pois_is_valid():
    schema = _load_schema("fpim_output_contract.schema.json")
    doc = {
        "fpim_output_id": "fpim-2",
        "flight_id": "FLT-002",
        "label_independent": True,
        "behavior_tags": [],
        "pois_along_path": [],
        "evidence_tier": "T3",
        "confidence": 0.2,
    }
    assert _validate(doc, schema) == []


def test_corrim_correlation_output_references_fpim_pois():
    schema = _load_schema("corrim_correlation_output.schema.json")
    doc = {
        "correlation_id": "corr-1",
        "satim_output_ids": ["satim-1"],
        "fpim_output_ids": ["fpim-1"],
        "contributing_poi_ids": ["fp-1"],
        "correlation_score": 0.75,
        "explanation": "SATIM tile-seam finding co-located with FPIM POI fp-1.",
        "operator_action": "review_context_only",
        "live_tracking": False,
    }
    assert _validate(doc, schema) == []


def test_corrim_correlation_output_rejects_missing_satim_ids():
    schema = _load_schema("corrim_correlation_output.schema.json")
    doc = {
        "correlation_id": "corr-2",
        "satim_output_ids": [],
        "fpim_output_ids": ["fpim-1"],
        "correlation_score": 0.5,
        "explanation": "missing satim evidence",
        "operator_action": "review_context_only",
        "live_tracking": False,
    }
    errors = _validate(doc, schema)
    assert any("minItems" in e or "at least 1" in e for e in errors)
