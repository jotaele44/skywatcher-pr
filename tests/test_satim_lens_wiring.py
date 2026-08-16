"""The artifact engine reading the declarative lens registry, end to end.

Covers the seam between Core (which owns lenses) and SATIM (which consumes them), and
the backward-compatibility guarantee that makes the change safe to land: an engine
constructed without a registry must behave exactly as it did before.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skywatcher.core.lenses import ThresholdRegistry, load_default_registries
from skywatcher.satim.artifacts.engine import ArtifactAssessmentEngine

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SCHEMA = REPO_ROOT / "schemas/satim_artifact_assessment_v2.schema.json"
V1_SCHEMA = REPO_ROOT / "schemas/satim_artifact_assessment_v1.schema.json"


def _payload(**overrides) -> dict:
    base = {
        "assessment_id": "lens-wiring-001",
        "source": {"source_type": "screenshot", "provenance_status": "partial"},
        "roi": {"target": {"description": "suspected seam"}},
        "candidate_artifacts": ["SATIM-A01"],
        "final_classification": "SATIM-A01",
        "confidence": {"score": 0.8, "level": "HIGH"},
        "interpretation_restriction": "GEOMETRY_DEGRADED",
    }
    base.update(overrides)
    return base


@pytest.fixture(scope="module")
def wired_engine() -> ArtifactAssessmentEngine:
    lenses, objectives = load_default_registries()
    thresholds = ThresholdRegistry()
    thresholds.load()
    return ArtifactAssessmentEngine(
        lens_registry=lenses,
        objective_profile=objectives.get("satellite_imagery_standard"),
        threshold_registry=thresholds,
    )


def test_engine_without_a_registry_reports_no_lens_data() -> None:
    """Backward compatibility: omitting the registry reproduces v1 behavior."""
    result = ArtifactAssessmentEngine().assess(_payload())
    assert result.lenses_applied == ()
    assert result.lens_coverage == ()
    assert result.unsatisfied_requirements == ()
    assert result.thresholds_applied == ()
    assert result.primary_class == "SATIM-A01"


def test_wired_engine_reports_unmet_requirements(wired_engine) -> None:
    """A run supplying no lens parameters must say what is missing, not stay silent."""
    result = wired_engine.assess(_payload())

    assert "satim.image_artifacts" in result.lenses_applied
    assert result.unsatisfied_requirements, "an unsupplied required lens must block"
    assert any("satim.image_artifacts" in reason for reason in result.unsatisfied_requirements)


def test_wired_engine_is_satisfied_when_parameters_are_supplied(wired_engine) -> None:
    result = wired_engine.assess(
        _payload(
            lens_parameters={
                "satim.image_artifacts": {
                    "source_type": "screenshot",
                    "roi_target": [0, 0, 10, 10],
                    "roi_local_control": [20, 20, 30, 30],
                    "roi_boundary_control": [40, 40, 50, 50],
                    "roi_remote_control": [60, 60, 70, 70],
                    "raw_source_compared": True,
                    "seam_score_threshold": 6.0,
                }
            },
            lens_inputs={"satim.image_artifacts": ["source_frame", "roi_target"]},
        )
    )
    assert result.unsatisfied_requirements == ()
    states = {entry["lens_id"]: entry["state"] for entry in result.lens_coverage}
    assert states["satim.image_artifacts"] == "SATISFIED"


def test_executed_thresholds_are_stamped_with_their_governance_status(wired_engine) -> None:
    """ADR v2.1 A2 - a consumer must be able to see a CANDIDATE-grade cutoff as one."""
    result = wired_engine.assess(_payload())
    stamped = {t["threshold_id"]: t for t in result.thresholds_applied}

    assert "SATIM-SEAM-SCORE-6.0" in stamped
    for stamp in stamped.values():
        assert set(stamp) == {"threshold_id", "value", "status"}
        assert stamp["status"] in {"EXECUTABLE_CANDIDATE", "VALIDATED", "CANONICAL"}


def test_rejected_restriction_request_is_surfaced_not_swallowed() -> None:
    """The gate's verdict used to be computed and discarded, degrading silently."""
    engine = ArtifactAssessmentEngine()
    # A12 floors at ALL_INFERENCE_SUSPENDED; NONE is a weakening request.
    result = engine.assess(
        _payload(
            candidate_artifacts=["SATIM-A12"],
            final_classification="SATIM-A12",
            interpretation_restriction="NONE",
        )
    )
    assert result.restriction_allowed is False
    assert result.restriction_reason
    assert "RESTRICTION_REQUEST_REJECTED" in result.rules_triggered
    # The restriction itself still lands on the mandatory floor.
    assert result.interpretation_restriction == "ALL_INFERENCE_SUSPENDED"


def test_accepted_restriction_request_records_that_it_was_honored() -> None:
    result = ArtifactAssessmentEngine().assess(_payload())
    assert result.restriction_allowed is True
    assert "RESTRICTION_REQUEST_REJECTED" not in result.rules_triggered


def test_v1_payload_is_valid_v2_and_lens_keys_need_v2() -> None:
    """v1 sets additionalProperties:false, which is why v2 exists at all."""
    jsonschema = pytest.importorskip("jsonschema")
    v1 = json.loads(V1_SCHEMA.read_text(encoding="utf-8"))
    v2 = json.loads(V2_SCHEMA.read_text(encoding="utf-8"))

    plain = _payload()
    jsonschema.validate(plain, v1)
    jsonschema.validate(plain, v2)

    with_lenses = _payload(lens_parameters={"satim.image_artifacts": {"roi_target": [0]}})
    jsonschema.validate(with_lenses, v2)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(with_lenses, v1)


def test_v2_adds_no_required_fields() -> None:
    """Every lens key is optional, so no existing producer is broken by v2."""
    v1 = json.loads(V1_SCHEMA.read_text(encoding="utf-8"))
    v2 = json.loads(V2_SCHEMA.read_text(encoding="utf-8"))
    assert v2["required"] == v1["required"]
