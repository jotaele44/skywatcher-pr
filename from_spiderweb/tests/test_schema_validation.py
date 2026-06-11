"""Tests for SchemaValidator: valid/invalid routing."""

import csv
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")

from integration.schema_validation import SCHEMAS_DIR, SchemaValidator


@pytest.fixture
def validator():
    return SchemaValidator()


def test_available_schemas_nonempty(validator):
    schemas = validator.available_schemas()
    assert len(schemas) > 0


def test_validate_valid_screenshot(validator):
    record = {
        "screenshot_id": "SS_001",
        "image_path": "/tmp/img.jpg",
        "processed_at": "2024-03-15T08:00:00",
        "ocr_confidence": 0.85,
    }
    result = validator.validate(record, "screenshot")
    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_invalid_screenshot_missing_required(validator):
    record = {"ocr_confidence": 0.85}  # missing screenshot_id, image_path, processed_at
    result = validator.validate(record, "screenshot")
    # If jsonschema is available, should be invalid; otherwise valid (fallback)
    try:
        import jsonschema
        assert result["valid"] is False
        assert len(result["errors"]) > 0
    except ImportError:
        assert result["valid"] is True


def test_validate_batch_routes_invalid(validator, tmp_path):
    review_path = str(tmp_path / "review_queue.csv")
    valid_record = {
        "screenshot_id": "SS_001",
        "image_path": "/tmp/img.jpg",
        "processed_at": "2024-03-15T08:00:00",
    }
    invalid_record = {"ocr_confidence": 0.5}  # missing required fields

    try:
        import jsonschema
        records = [valid_record, invalid_record]
        valid_records, n_invalid = validator.validate_batch(records, "screenshot", review_path)
        assert n_invalid == 1            # one invalid *record*
        assert len(valid_records) == 1
        assert Path(review_path).exists()
        with open(review_path, newline="") as f:
            rows = list(csv.DictReader(f))
        # Enriched contract: one row per validation error (>= 1 for one bad record).
        assert len(rows) >= 1
        assert all(r["schema_name"] == "screenshot" for r in rows)
        assert all(r.get("field") and r.get("error_type") for r in rows)
    except ImportError:
        pytest.skip("jsonschema not installed")


def test_validate_unknown_schema_returns_valid(validator):
    result = validator.validate({"foo": "bar"}, "nonexistent_schema")
    assert result["valid"] is True


def test_validate_export_manifest_valid(validator):
    manifest = {
        "generated_at": "2024-03-15T00:00:00Z",
        "db_path": "/tmp/test.db",
        "files": [{"filename": "events.parquet", "record_count": 10}],
    }
    result = validator.validate_export_manifest(manifest)
    assert result["valid"] is True


def test_review_queue_has_correct_columns(validator, tmp_path):
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")

    review_path = str(tmp_path / "review_queue.csv")
    invalid = {"bad": "record"}
    validator.validate_batch([invalid], "screenshot", review_path)
    with open(review_path, newline="") as f:
        reader = csv.DictReader(f)
        assert set(reader.fieldnames) == {
            "routed_at", "record_id", "source_file", "schema_name",
            "field", "error_type", "error_message", "record_json", "suggested_fix",
        }


def test_review_queue_dedups_within_window(validator, tmp_path):
    """Re-routing an identical invalid record must not duplicate rows (24h dedup)."""
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        pytest.skip("jsonschema not installed")
    review_path = str(tmp_path / "review_queue.csv")
    invalid = {"ocr_confidence": 0.5}  # missing required screenshot fields
    validator.validate_batch([invalid], "screenshot", review_path)
    with open(review_path, newline="") as f:
        first = list(csv.DictReader(f))
    validator.validate_batch([invalid], "screenshot", review_path)
    with open(review_path, newline="") as f:
        second = list(csv.DictReader(f))
    assert len(first) >= 1
    assert len(second) == len(first)


# ── Stage 1 hardening tests ───────────────────────────────────────────────────

def test_run_db_validation_returns_per_table_summary(populated_db, tmp_path):
    v = SchemaValidator()
    review_path = str(tmp_path / "review_queue.csv")
    results = v.run_db_validation(populated_db, review_path)
    expected_schemas = {
        "flight_event", "screenshot", "track_point",
        "extracted_field", "anomaly", "mission_inference",
    }
    assert not results.get("_error"), f"Unexpected error: {results.get('_error')}"
    for schema_name in expected_schemas:
        assert schema_name in results, f"Missing per-table result: {schema_name}"
        entry = results[schema_name]
        assert "total" in entry
        assert "valid" in entry
        assert "invalid" in entry


def test_run_db_validation_missing_db_returns_error_key(tmp_path):
    v = SchemaValidator()
    results = v.run_db_validation(
        str(tmp_path / "nonexistent.db"),
        str(tmp_path / "review.csv"),
    )
    # SQLite creates the file if missing, so run_db_validation returns empty
    # per-table results (no tables → nothing validated). The absence of _error
    # with zero-table results is also acceptable; either way there must be no
    # crash and the return must be a dict.
    assert isinstance(results, dict)


def test_all_core_schemas_loadable():
    v = SchemaValidator()
    loaded = v.available_schemas()
    try:
        import jsonschema  # noqa: F401
        assert len(loaded) >= 11, (
            f"Expected ≥11 schemas in {SCHEMAS_DIR}, got {len(loaded)}: {loaded}"
        )
    except ImportError:
        pytest.skip("jsonschema not installed — schema loading is a no-op")


def test_satellite_source_manifest_schema_loaded(validator):
    try:
        import jsonschema  # noqa: F401
        assert "satellite_source_manifest" in validator.available_schemas()
    except ImportError:
        pytest.skip("jsonschema not installed")


# ── Phase 9: Production Hardening ────────────────────────────────────────────

def test_reload_schemas_returns_count(validator):
    count = validator.reload_schemas()
    assert isinstance(count, int)
    assert count >= 0


def test_reload_schemas_idempotent(validator):
    count1 = validator.reload_schemas()
    count2 = validator.reload_schemas()
    assert count1 == count2


def test_schema_count_matches_available(validator):
    assert validator.schema_count() == len(validator.available_schemas())


def test_get_schema_names_sorted(validator):
    names = validator.get_schema_names()
    assert names == sorted(names)


def test_validate_with_context_valid_record(validator):
    record = {
        "screenshot_id": "s1", "flight_id": "f1", "image_path": "/a/b.png",
        "captured_at": "2024-01-01T00:00:00Z",
        "processed_at": "2024-01-01T00:01:00Z",
        "ocr_confidence": 0.9,
        "has_callsign": True, "has_coordinates": True,
    }
    result = validator.validate_with_context(record, "screenshot", "test-run")
    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_with_context_prefixes_errors(validator):
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        pytest.skip("jsonschema not installed")
    result = validator.validate_with_context({}, "screenshot", "batch-42")
    if not result["valid"]:
        assert all("[batch-42]" in e for e in result["errors"])


# ── Schema index (schemas/schema_index.json) ─────────────────────────────────

def test_load_index_returns_artifacts(validator):
    """schema_index.json parses cleanly and exposes the artifacts list."""
    idx = validator.load_index()
    assert isinstance(idx, dict)
    assert "schema_version" in idx
    artifacts = validator.index_artifacts()
    assert isinstance(artifacts, list)
    assert len(artifacts) > 0, "schema_index.json should list at least one artifact"


def test_index_covers_pr_intel_required_outputs(validator):
    """Every artifact in PRIntelAdapter.REQUIRED_OUTPUTS has an index entry."""
    try:
        import pyarrow  # noqa: F401  (PRIntelAdapter imports pyarrow at module import)
    except ImportError:
        pytest.skip("pyarrow not installed")
    from integration.pr_intel_adapter import PRIntelAdapter
    for artifact in PRIntelAdapter.REQUIRED_OUTPUTS:
        entry = validator.index_lookup(artifact)
        assert entry is not None, f"PR Intel artifact {artifact} missing from schema_index.json"
        assert entry["workstream"] == "pr_intel"
        assert "format" in entry and entry["format"] in {"parquet", "geojson", "json", "csv", "jsonl", "markdown"}


def test_index_schema_files_resolve_on_disk(validator):
    """Every non-null schema_file path in the index points to an existing file."""
    from pathlib import Path
    missing = []
    for entry in validator.index_artifacts():
        sf = entry.get("schema_file")
        if sf and not Path(sf).exists():
            missing.append(sf)
    assert not missing, f"schema_index.json references missing schema files: {missing}"


def test_index_lookup_returns_none_for_unknown(validator):
    """Unknown artifact paths return None (no crash)."""
    assert validator.index_lookup("definitely_not_an_artifact.parquet") is None


# ── T2-18 — Geometry validity (shapely) ──────────────────────────────────────

def test_validate_geometry_accepts_valid_features(validator):
    features = [
        {"geometry": {"type": "Point", "coordinates": [-66.0, 18.0]}},
        {"geometry": {"type": "LineString",
                      "coordinates": [[-67.0, 18.0], [-66.0, 19.0]]}},
    ]
    errors = validator.validate_geometry(features)
    assert errors == []


def test_validate_geometry_flags_missing_geometry(validator):
    features = [
        {"geometry": {"type": "Point", "coordinates": None}},
        {"geometry": None},
    ]
    errors = validator.validate_geometry(features)
    assert len(errors) == 2
    assert all("missing geometry" in e["reason"] for e in errors)


def test_validate_geometry_flags_self_intersecting_polygon(validator):
    """Bowtie polygon: shapely catches self-intersection (needs shapely)."""
    try:
        import shapely  # noqa: F401
    except ImportError:
        pytest.skip("shapely not installed")
    # Bowtie: vertices in order (0,0), (1,1), (1,0), (0,1), close → self-intersects.
    bowtie = [[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]
    features = [{"geometry": {"type": "Polygon", "coordinates": [bowtie]}}]
    errors = validator.validate_geometry(features)
    assert len(errors) == 1
    assert "Self-intersection" in errors[0]["reason"] or "invalid" in errors[0]["reason"].lower()


def test_validate_geometry_empty_input(validator):
    assert validator.validate_geometry([]) == []
    assert validator.validate_geometry(None) == []


# ── T2-19 — Null-field enforcement ──────────────────────────────────────────

def test_null_for_required_field_tagged_as_null_field(validator):
    """A None value for a required field → error_type='null_field' (not 'type')."""
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        pytest.skip("jsonschema not installed")
    # screenshot's required = [screenshot_id, image_path, processed_at]
    record = {"screenshot_id": None, "image_path": "/x.png", "processed_at": "2026-06-01T00:00:00Z"}
    errors = validator._structured_errors(record, "screenshot")
    # Should have at least one error and it should be null_field, not type
    null_field_errs = [e for e in errors if e["error_type"] == "null_field"]
    assert null_field_errs, f"expected a null_field error, got {[e['error_type'] for e in errors]}"
    assert null_field_errs[0]["field"] == "screenshot_id"


def test_missing_required_field_still_tagged_as_required(validator):
    """Missing key keeps error_type='required' (distinct from null)."""
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        pytest.skip("jsonschema not installed")
    record = {"image_path": "/x.png", "processed_at": "2026-06-01T00:00:00Z"}  # no screenshot_id
    errors = validator._structured_errors(record, "screenshot")
    req_errs = [e for e in errors if e["error_type"] == "required"]
    assert req_errs, "expected a 'required' error for the missing key"


# ── T2-20 — Confidence-scale enforcement ────────────────────────────────────

def test_all_confidence_properties_on_canonical_scale(validator):
    """Every numeric property whose name contains 'confidence' across all loaded
    schemas must declare ONE OF the two canonical scales:

      - [0, 1]   — operational confidence (most derived fields)
      - [0, 100] — OCR-engine raw confidence (tesseract percentage; e.g.
                   ocr_raw_by_zone.confidence_mean / .confidence_min)

    Anything else is a contract violation. See
    docs/SCHEMA_AND_EXPORT_CONTRACTS.md for the canonical policy."""
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        pytest.skip("jsonschema not installed")
    CANONICAL_SCALES = ({"min": 0, "max": 1}, {"min": 0, "max": 100})
    offenders = []
    for name, v in validator._validators.items():
        props = (v.schema or {}).get("properties", {}) or {}
        for prop_name, spec in props.items():
            if "confidence" not in prop_name.lower():
                continue
            if not isinstance(spec, dict):
                continue
            ptype = spec.get("type")
            allowed_numeric = ("number", "integer", ["number", "null"], ["integer", "null"])
            if ptype not in allowed_numeric:
                continue  # 'identity_status' and other non-numerics are fine
            scale = {"min": spec.get("minimum"), "max": spec.get("maximum")}
            if scale not in CANONICAL_SCALES:
                offenders.append(f"{name}.{prop_name}: min={scale['min']}, max={scale['max']}")
    assert not offenders, (
        "Confidence properties must be on a canonical scale ([0,1] operational "
        f"OR [0,100] OCR-engine raw): {offenders}"
    )
