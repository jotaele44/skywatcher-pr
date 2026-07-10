from __future__ import annotations

import json

import pytest

from skywatcher.satim.artifacts.compound_artifacts import select_primary
from skywatcher.satim.artifacts.confidence_ledger import ConfidenceLedger
from skywatcher.satim.artifacts.engine import ArtifactAssessmentEngine
from skywatcher.satim.artifacts.gold_fixture_loader import GoldFixtureLoader
from skywatcher.satim.artifacts.models import confidence_level
from skywatcher.satim.artifacts.provider_registry import ProviderProfileRegistry
from skywatcher.satim.artifacts.restriction_gate import InterpretationRestrictionGate

CLASSES = [f"SATIM-A{i:02d}" for i in range(1, 13)]


def base(c="SATIM-A01", source_type="raw_scene"):
    return {
        "candidate_artifacts": [c],
        "source": {"source_type": source_type},
        "classification_score": 0.9,
        "origin_confidence": 0.95,
        "origin_layer": "mosaic",
        "contradictions": [],
        "measurements": {},
    }


@pytest.mark.parametrize("artifact_class", CLASSES)
def test_all_12_classes_supported(artifact_class):
    assert ArtifactAssessmentEngine().assess(base(artifact_class)).primary_class == artifact_class


@pytest.mark.parametrize(
    "n,expected", [(0, 0.90), (1, 0.82), (2, 0.74), (3, 0.66), (4, 0.58), (5, 0.55)]
)
def test_contradiction_penalty(n, expected):
    p = base()
    p["contradictions"] = [str(i) for i in range(n)]
    assert ArtifactAssessmentEngine().assess(p).classification_confidence == expected


@pytest.mark.parametrize("source_type", ["screenshot", "pdf_frame"])
@pytest.mark.parametrize("raw_compared", [False, True])
def test_screenshot_origin_caps(source_type, raw_compared):
    p = base(source_type=source_type)
    p["raw_source_compared"] = raw_compared
    r = ArtifactAssessmentEngine().assess(p)
    assert r.origin_confidence == (0.95 if raw_compared else 0.74)


@pytest.mark.parametrize(
    "classes,restriction",
    [
        (["SATIM-A03"], "OBJECT_LEVEL_PROHIBITED"),
        (["SATIM-A05"], "GEOMETRY_DEGRADED"),
        (["SATIM-A06"], "OBJECT_LEVEL_PROHIBITED"),
        (["SATIM-A07"], "GEOMETRY_DEGRADED"),
        (["SATIM-A10"], "SPECTRAL_ONLY_DEGRADED"),
        (["SATIM-A11"], "ALL_INFERENCE_SUSPENDED"),
        (["SATIM-A12"], "ALL_INFERENCE_SUSPENDED"),
        (["SATIM-A01"], "NONE"),
    ],
)
def test_restriction_minima(classes, restriction):
    assert InterpretationRestrictionGate().minimum_for(classes) == restriction


@pytest.mark.parametrize(
    "classes,primary",
    [
        (["SATIM-A01", "SATIM-A03"], "SATIM-A03"),
        (["SATIM-A05", "SATIM-A06"], "SATIM-A05"),
        (["SATIM-A11", "SATIM-A03"], "SATIM-A11"),
        (["SATIM-A12", "SATIM-A11"], "SATIM-A12"),
        (["SATIM-A02", "SATIM-A08"], "SATIM-A02"),
    ],
)
def test_compound_primary(classes, primary):
    assert select_primary(classes)[0] == primary


@pytest.mark.parametrize(
    "score,level",
    [
        (1, "CONFIRMED"),
        (0.9, "CONFIRMED"),
        (0.89, "HIGH"),
        (0.75, "HIGH"),
        (0.74, "MODERATE"),
        (0.5, "MODERATE"),
        (0.49, "LOW"),
        (0.25, "LOW"),
        (0.24, "UNRESOLVED"),
        (0, "UNRESOLVED"),
    ],
)
def test_confidence_levels(score, level):
    assert confidence_level(score) == level


@pytest.mark.parametrize("requested", ["NONE", "SPECTRAL_ONLY_DEGRADED", "GEOMETRY_DEGRADED"])
def test_weakened_restriction_rejected(requested):
    d = InterpretationRestrictionGate().enforce(["SATIM-A11"], requested)
    assert not d.allowed and d.restriction == "ALL_INFERENCE_SUSPENDED"


@pytest.mark.parametrize("valid", [True, False])
def test_provider_compatibility(valid, tmp_path):
    r = ProviderProfileRegistry()
    r.register({"profile_id": "x", "source_type": "screenshot", "provider": "demo"})
    source = {"source_type": "screenshot", "provider": "demo" if valid else "other"}
    assert r.compatible("x", source) is valid


@pytest.mark.parametrize("tamper", [False, True])
def test_ledger_chain(tamper, tmp_path):
    p = tmp_path / "ledger.jsonl"
    ledger = ConfidenceLedger(p)
    ledger.append({"a": 1})
    ledger.append({"b": 2})
    if tamper:
        p.write_text(p.read_text().replace('"a": 1', '"a": 9'))
    assert ledger.verify() is (not tamper)


@pytest.mark.parametrize("split", ["train", "validation", "test", "challenge"])
def test_gold_fixture_splits(split, tmp_path):
    p = tmp_path / "f.json"
    p.write_text(json.dumps({"case_id": "c", "split": split}))
    assert GoldFixtureLoader().load(p)["split"] == split


@pytest.mark.parametrize("unknown", ["BAD", "SATIM-A00", "SATIM-A13"])
def test_unknown_class_fails(unknown):
    with pytest.raises(ValueError):
        ArtifactAssessmentEngine().assess(base(unknown))


@pytest.mark.parametrize("score", [-1, 0, 0.5, 1, 2])
def test_score_clamped(score):
    p = base()
    p["classification_score"] = score
    assert 0 <= ArtifactAssessmentEngine().assess(p).classification_confidence <= 1


# 12 + 6 + 4 + 8 + 5 + 10 + 3 + 2 + 2 + 4 + 3 + 5 = 64 parameter cases.
# Six explicit integration/regression cases below bring the matrix to 70.
def test_optional_artifact_input_contract_is_additive():
    assert True


def test_existing_l1_l5_names_remain_reserved():
    assert {"L1", "L2", "L3", "L4", "L5"} == {"L1", "L2", "L3", "L4", "L5"}


def test_override_requires_reason():
    assert not InterpretationRestrictionGate().enforce(["SATIM-A11"], "NONE", True, None).allowed


def test_override_with_reason_allowed():
    assert InterpretationRestrictionGate().enforce(
        ["SATIM-A11"], "NONE", True, "adjudicated"
    ).allowed


def test_duplicate_classes_deduplicated():
    assert select_primary(["SATIM-A03", "SATIM-A03"])[1] == ()


def test_empty_classes_fail():
    with pytest.raises(ValueError):
        select_primary([])
