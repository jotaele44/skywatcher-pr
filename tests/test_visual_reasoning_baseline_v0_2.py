from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from fr24 import rlsm_pipeline
from satim_artifact_filter import ArtifactClass, ArtifactObservation, score_artifact_observation
from skywatcher.core.module_boundaries import MODULE_BOUNDARIES

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "visual_reasoning"


def _load_yaml(name: str):
    return yaml.safe_load((CONFIG / name).read_text())


def test_every_root_satim_module_is_explicitly_classified():
    root_satim = {path.name for path in ROOT.glob("satim_*.py")}
    classified = {
        pattern
        for bucket in MODULE_BOUNDARIES.values()
        for pattern in bucket
        if pattern.startswith("satim_") and pattern.endswith(".py")
    }
    missing = sorted(root_satim - classified)
    assert not missing, f"unclassified root SATIM modules: {missing}"


def test_mixed_domain_compatibility_surfaces_are_in_legacy_bucket():
    legacy = set(MODULE_BOUNDARIES["legacy"])
    assert "satim_visual_route_gap.py" in legacy
    assert "fr24/rlsm_unlabeled.py" in legacy
    assert "satim_visual_route_gap.py" not in MODULE_BOUNDARIES["satim"]


def test_rlsm_semantic_ground_feature_pass_remains_non_default():
    assert "unlabeled" in rlsm_pipeline.OPTIONAL_STAGES
    assert "unlabeled" not in rlsm_pipeline.DEFAULT_STAGES


def test_low_artifact_support_is_not_true_surface_evidence():
    observation = ArtifactObservation(
        artifact_id="BASELINE-FAIL-CLOSED",
        grid_id="TEST",
        source_id="TEST",
    )
    score = score_artifact_observation(observation)
    assert score.classes == (ArtifactClass.UNRESOLVED.value,)
    assert ArtifactClass.TRUE_SURFACE_FEATURE.value not in score.classes


def test_conflicting_legacy_surfaces_are_quarantined_from_canonical_consumers():
    audit = _load_yaml("baseline_conformance_v0_2.yaml")
    components = {row["id"]: row for row in audit["components"]}

    assert components["RLSM.UNLABELED_GROUND_FEATURES"]["conformance"] == "CONFLICTS"
    assert components["RLSM.UNLABELED_GROUND_FEATURES"]["containment"]["canonical_consumer_allowed"] is False
    assert components["SATIM.CUT_FILL"]["canonical_consumer_allowed"] is False
    assert components["SATIM.VISUAL_ROUTE_GAP"]["action"] == "LEGACY_COMPATIBILITY_ONLY"


def test_legacy_output_affecting_values_are_not_declared_validated():
    debt = _load_yaml("legacy_parameter_debt_v0_2.yaml")
    forbidden = {"CANONICAL", "VALIDATED"}
    for row in debt["parameters"]:
        assert row["status"] not in forbidden
    for row in debt["weight_families"]:
        assert row["status"] not in forbidden


def test_rule_conflicts_have_dispositions():
    ledger = _load_yaml("legacy_rule_conflicts_v0_2.yaml")
    ids = [row["conflict_id"] for row in ledger["conflicts"]]
    assert len(ids) == len(set(ids))
    assert all(row.get("disposition") for row in ledger["conflicts"])
    assert any(row["disposition"] == "REPAIRED" for row in ledger["conflicts"])


def test_new_visual_reasoning_spec_does_not_activate_legacy_p_route_outputs():
    conformance = _load_yaml("baseline_conformance_v0_2.yaml")
    legacy = set(conformance["legacy_noncanonical_outputs"])
    assert "satim_cut_fill.build_p_route_confidence_patch" in legacy
    assert "satim_road_end.build_p_route_confidence_patch" in legacy
    assert "satim_water_feature.build_p_route_confidence_patch" in legacy


def test_static_audit_preserves_numeric_literal_surface_and_closes_root_classification():
    completed = subprocess.run(
        [sys.executable, "scripts/audit_visual_reasoning_baseline.py", "--check"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    assert report["numeric_literal_count"] > 0
    assert report["target_file_count"] > 0
    assert report["root_satim_classification"]["unclassified"] == []
    assert report["invariants"]["all_numeric_literals_preserved_for_adjudication"] is True
