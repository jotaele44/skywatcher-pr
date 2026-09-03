"""Regression tests that exercise the SATIM artifact protocol through its
committed JSON schemas, not just inline dicts.

Each test pins a place where schema-valid inputs previously diverged from the
runtime code (raw-source flag, provider source_types, gold-fixture scene_id,
ledger-entry shape), so those contracts cannot silently drift apart again.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skywatcher.satim.artifacts.cli import build_ledger_entry
from skywatcher.satim.artifacts.confidence_ledger import ConfidenceLedger
from skywatcher.satim.artifacts.engine import ArtifactAssessmentEngine
from skywatcher.satim.artifacts.gold_fixture_loader import GoldFixtureLoader
from skywatcher.satim.artifacts.provider_registry import ProviderProfileRegistry
from skywatcher.satim.artifacts.schema_validator import ArtifactSchemaValidator

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = REPO_ROOT / "schemas"
PROFILES = REPO_ROOT / "profiles"


def _assessment(**overrides):
    payload = {
        "assessment_id": "conf-001",
        "source": {"source_type": "screenshot", "provenance_status": "partial"},
        "roi": {"target": {"description": "target roi"}},
        "candidate_artifacts": ["SATIM-A01"],
        "final_classification": "SATIM-A01",
        "confidence": {"score": 0.9, "level": "CONFIRMED"},
        "interpretation_restriction": "NONE",
    }
    payload.update(overrides)
    return payload


def test_raw_source_compared_is_schema_valid_and_lifts_the_cap():
    validator = ArtifactSchemaValidator(SCHEMAS / "satim_artifact_assessment_v1.schema.json")
    engine = ArtifactAssessmentEngine()

    without_flag = _assessment()
    validator.require_valid(without_flag)
    assert engine.assess(without_flag).origin_confidence == 0.74

    with_flag = _assessment(raw_source_compared=True)
    validator.require_valid(with_flag)  # rejected before the schema fix
    assert engine.assess(with_flag).origin_confidence == 0.9


def test_committed_provider_profile_enforces_source_types():
    validator = ArtifactSchemaValidator(SCHEMAS / "satim_provider_profile_v1.schema.json")
    profile = json.loads((PROFILES / "generic_screenshot_v1.json").read_text(encoding="utf-8"))
    validator.require_valid(profile)

    registry = ProviderProfileRegistry()
    registry.register(profile)
    assert registry.compatible(
        "generic_screenshot_v1", {"source_type": "screenshot", "provider": "generic"}
    )
    # raw_scene is not in the profile's source_types -> must be rejected.
    assert not registry.compatible(
        "generic_screenshot_v1", {"source_type": "raw_scene", "provider": "generic"}
    )


def _fixture(fixture_id, split, scene_id):
    return {
        "fixture_id": fixture_id,
        "fixture_type": "positive",
        "artifact_class": "SATIM-A01",
        "split": split,
        "scene_id": scene_id,
        "roi": {},
        "expected_decision": {},
        "adjudication_status": "adjudicated",
    }


def test_gold_fixture_leakage_guard_reads_top_level_scene_id():
    validator = ArtifactSchemaValidator(SCHEMAS / "satim_gold_fixture_v1.schema.json")
    loader = GoldFixtureLoader()

    leaking = [_fixture("f1", "train", "S1"), _fixture("f2", "test", "S1")]
    for fixture in leaking:
        validator.require_valid(fixture)
    with pytest.raises(ValueError):
        loader.assert_no_scene_leakage(leaking)

    clean = [_fixture("f3", "train", "S2"), _fixture("f4", "test", "S3")]
    loader.assert_no_scene_leakage(clean)  # distinct scenes -> no leakage


def test_cli_ledger_entries_validate_against_ledger_schema(tmp_path):
    validator = ArtifactSchemaValidator(
        SCHEMAS / "satim_confidence_ledger_entry_v1.schema.json"
    )
    result = ArtifactAssessmentEngine().assess(_assessment()).to_dict()

    path = tmp_path / "ledger.jsonl"
    ledger = ConfidenceLedger(path)
    ledger.append(build_ledger_entry(_assessment(assessment_id="conf-001"), result))
    ledger.append(build_ledger_entry(_assessment(assessment_id="conf-002"), result))

    assert ledger.verify()
    lines = [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 2
    for line in lines:
        validator.require_valid(json.loads(line))
