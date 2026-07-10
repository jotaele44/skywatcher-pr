"""Tests for automatic chaining of the SATIM artifact protocol into an engine run.

Covers the pure L5->assessment mapping, the end-to-end auto-derivation through
``run_satim_engine`` (assessment + confidence ledger + provider compatibility),
and non-interference when no L5 candidate denotes an artifact.
"""

from __future__ import annotations

import json
from pathlib import Path

from fr24 import satim_engine
from skywatcher.satim.artifacts.confidence_ledger import ConfidenceLedger
from skywatcher.satim.artifacts.pipeline_chain import build_assessment_from_l5
from skywatcher.satim.artifacts.schema_validator import ArtifactSchemaValidator

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = REPO_ROOT / "schemas"

STRONG_TILE_SEAM_ROW = (
    "straight_boundary_score,radiometric_discontinuity_score,texture_discontinuity_score,"
    "rectangular_patch_score,multi_date_persistence,dem_hillshade_alignment,right_angle_score\n"
    "0.95,0.9,0.7,0.7,0.1,0.1,0.0\n"
)


def _assessment_validator() -> ArtifactSchemaValidator:
    return ArtifactSchemaValidator(SCHEMAS / "satim_artifact_assessment_v1.schema.json")


def test_build_assessment_maps_tile_seam_to_a01():
    scored = [
        {"decision": "probable_ground_feature", "persistent_ground_feature_likelihood": 0.8},
        {"decision": "probable_tile_seam", "tile_seam_likelihood": 0.82},
    ]
    payload = build_assessment_from_l5(scored)
    assert payload is not None
    assert payload["candidate_artifacts"] == ["SATIM-A01"]
    assert payload["confidence"]["score"] == 0.82
    assert payload["origin_layer"] == "mosaic"
    # Taxonomy: object interpretation across a seam requires verified
    # geometric continuity, which auto-derivation cannot provide.
    assert payload["interpretation_restriction"] == "GEOMETRY_DEGRADED"
    _assessment_validator().require_valid(payload)


def test_build_assessment_maps_cloud_shadow_to_a09():
    scored = [{"decision": "probable_cloud_shadow", "cloud_shadow_likelihood": 0.6}]
    payload = build_assessment_from_l5(scored)
    assert payload is not None
    assert payload["candidate_artifacts"] == ["SATIM-A09"]
    assert payload["origin_layer"] == "atmosphere"
    # Taxonomy: feature absence cannot be inferred inside obscured/masked
    # regions, so object-level interpretation is prohibited in the ROI.
    assert payload["interpretation_restriction"] == "OBJECT_LEVEL_PROHIBITED"
    _assessment_validator().require_valid(payload)


def test_build_assessment_returns_none_for_non_artifact_decisions():
    scored = [
        {"decision": "probable_ground_feature", "persistent_ground_feature_likelihood": 0.9},
        {"decision": "indeterminate"},
        {"decision": "probable_terrain_shadow", "terrain_shadow_likelihood": 0.7},
    ]
    assert build_assessment_from_l5(scored) is None


def _run(tmp_path: Path, l5_csv_text: str):
    screenshots = tmp_path / "screenshots"
    screenshots.mkdir()
    l5_csv = tmp_path / "l5_candidates.csv"
    l5_csv.write_text(l5_csv_text, encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "satim.engine.input.v1",
                "run_id": "chain_test",
                "input_profile": "fr24_screenshot_batch",
                "inputs": {
                    "screenshots_dir": str(screenshots),
                    "l5_candidates_csv": str(l5_csv),
                },
                "options": {"export_legacy_readiness": True},
                "outputs": {"run_dir": str(tmp_path / "out")},
            }
        ),
        encoding="utf-8",
    )
    manifest = satim_engine.load_manifest(manifest_path)
    return satim_engine.run_satim_engine(manifest, tmp_path / "out")


def test_engine_auto_derives_assessment_and_ledger(tmp_path):
    summary = _run(tmp_path, STRONG_TILE_SEAM_ROW)
    outputs = summary["outputs"]

    assert outputs["artifact_assessment_auto_derived"] is True
    assert outputs["artifact_assessment_error"] is None

    result = json.loads(Path(outputs["artifact_assessment"]).read_text(encoding="utf-8"))
    assert result["auto_derived"] is True
    assert result["primary_class"] == "SATIM-A01"
    # screenshot source -> origin confidence capped at 0.74
    assert result["origin_confidence"] == 0.74
    assert "SCREENSHOT_ORIGIN_CAP_0_74" in result["rules_triggered"]
    # Class-derived restriction survives the gate into the persisted result.
    assert result["interpretation_restriction"] == "GEOMETRY_DEGRADED"

    ledger_path = Path(outputs["confidence_ledger"])
    assert ledger_path.exists()
    validator = ArtifactSchemaValidator(SCHEMAS / "satim_confidence_ledger_entry_v1.schema.json")
    lines = [x for x in ledger_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert lines
    for line in lines:
        validator.require_valid(json.loads(line))
    assert ConfidenceLedger(ledger_path).verify()

    # Provider profiles are loaded and their compatibility with the derived
    # source is recorded (the bundled "generic" profile requires a known
    # provider, which an auto-derived source does not claim, so the recorded
    # value is simply a boolean rather than a forced match).
    compat = outputs["artifact_provider_compatibility"]
    assert compat is not None
    generic = next(c for c in compat if c["profile_id"] == "generic_screenshot_v1")
    assert isinstance(generic["compatible"], bool)


def test_engine_no_candidates_is_non_interfering(tmp_path):
    header_only = (
        "straight_boundary_score,radiometric_discontinuity_score,texture_discontinuity_score\n"
    )
    summary = _run(tmp_path, header_only)
    outputs = summary["outputs"]

    assert outputs["artifact_assessment"] is None
    assert outputs["artifact_assessment_auto_derived"] is False
    assert outputs["confidence_ledger"] is None
    assert outputs["artifact_assessment_error"] is None
    assert not (tmp_path / "out" / "artifact_assessment_result.json").exists()
