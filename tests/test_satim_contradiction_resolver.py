from copy import deepcopy

from satim_contradiction_resolver import (
    ConflictType,
    ContradictionObservation,
    DetectorEvidence,
    DetectorType,
    EVIDENCE_RECONCILIATION_ONLY_NO_FACT_SYNTHESIS,
    ORIGINAL_OUTPUT_IMMUTABILITY,
    ReconciliationClass,
    build_contradiction_ledger,
    build_detector_confidence_patch,
    build_human_review_queue,
    contradiction_resolver_schema,
    score_contradiction,
)


def evidence(detector: DetectorType, record_id: str, classification: str, score: float = 0.8):
    return DetectorEvidence(
        detector=detector,
        record_id=record_id,
        classification=classification,
        score=score,
        geometry_id="GRID-001",
        timestamp_local="2026-07-19T12:00:00-04:00",
        links=("GRID-001",),
        provenance={"source": detector.value, "record_id": record_id},
        artifact_confidence=0.1,
    )


def fixture(kind: str) -> ContradictionObservation:
    sources = (
        evidence(DetectorType.PATCHWORK_POI, "PATCH-001", "MAINTAINED_PATCHWORK"),
        evidence(DetectorType.ROAD_END_NODE, "ROAD-001", "ACCESS_NODE"),
        evidence(DetectorType.CUT_FILL_FEATURE, "CUT-001", "CONSTRUCTION_PAD"),
        evidence(DetectorType.LINEAR_CORRIDOR, "LINEAR-001", "ACCESS_CORRIDOR"),
        evidence(DetectorType.WATER_FEATURE, "WATER-001", "UNKNOWN_WATER"),
        evidence(DetectorType.ARTIFACT_CONFIDENCE_PATCH, "ART-001", "TRUE_SURFACE_FEATURE"),
    )
    conflicts = {
        "consistent": {},
        "soft": {ConflictType.CLASS_CONFLICT: 0.45},
        "hard": {ConflictType.GEOMETRY_CONFLICT: 0.9},
        "artifact": {ConflictType.ARTIFACT_CONFLICT: 0.8},
        "temporal": {ConflictType.TEMPORAL_CONFLICT: 0.65},
        "provenance": {ConflictType.PROVENANCE_CONFLICT: 0.55},
    }
    if kind == "insufficient":
        return ContradictionObservation(
            reconciliation_id="REC-INSUFFICIENT",
            evidence=(sources[0],),
            conflict_strengths={},
        )
    if kind == "provenance":
        missing = DetectorEvidence(
            detector=DetectorType.WATER_FEATURE,
            record_id="WATER-002",
            classification="UNKNOWN_WATER",
            score=0.5,
            provenance={},
        )
        return ContradictionObservation(
            reconciliation_id="REC-PROVENANCE",
            evidence=(sources[0], missing),
            conflict_strengths=conflicts[kind],
        )
    return ContradictionObservation(
        reconciliation_id=f"REC-{kind.upper()}",
        evidence=sources,
        conflict_strengths=conflicts[kind],
        notes="Synthetic reconciliation fixture.",
    )


def test_schema_contract_and_guardrails():
    schema = contradiction_resolver_schema()
    assert schema["resolver"] == "SATIM_SURFACE_FEATURE_CONTRADICTION_RESOLVER_v1"
    assert schema["guardrail"] == EVIDENCE_RECONCILIATION_ONLY_NO_FACT_SYNTHESIS
    assert schema["immutability_rule"] == ORIGINAL_OUTPUT_IMMUTABILITY
    assert set(schema["conflict_types"]) == {item.value for item in ConflictType}
    assert set(schema["classes"]) == {item.value for item in ReconciliationClass}
    assert set(schema["detectors"]) == {item.value for item in DetectorType}
    assert "SYNTHESIZED_FACT" in schema["prohibited_outputs"]
    assert "SOURCE_RECORD_MUTATION" in schema["prohibited_outputs"]


def test_required_reconciliation_classes_are_emitted():
    assert score_contradiction(fixture("consistent")).classification == "CONSISTENT"
    assert score_contradiction(fixture("soft")).classification == "SOFT_CONTRADICTION"
    assert score_contradiction(fixture("hard")).classification == "HARD_CONTRADICTION"
    assert score_contradiction(fixture("insufficient")).classification == "INSUFFICIENT_EVIDENCE"


def test_artifact_temporal_and_provenance_conflicts_are_auditable():
    artifact = score_contradiction(fixture("artifact"))
    temporal = score_contradiction(fixture("temporal"))
    provenance = score_contradiction(fixture("provenance"))
    assert "ARTIFACT_CONFLICT" in artifact.conflict_types
    assert "TEMPORAL_CONFLICT" in temporal.conflict_types
    assert "PROVENANCE_CONFLICT" in provenance.conflict_types
    assert "MISSING_SOURCE_PROVENANCE" in provenance.review_reasons


def test_original_outputs_are_immutable_and_preserved_in_ledger():
    source = fixture("hard")
    before = deepcopy(source)
    ledger = build_contradiction_ledger([source])
    assert source == before
    assert len(ledger) == 1
    rows = ledger[0]["source_evidence"]
    assert [row["classification"] for row in rows] == [item.classification for item in source.evidence]
    assert [row["score"] for row in rows] == [item.score for item in source.evidence]
    assert all(row["provenance"] for row in rows)
    assert ledger[0]["immutability_rule"] == ORIGINAL_OUTPUT_IMMUTABILITY


def test_confidence_patch_is_non_destructive_and_separable():
    source = fixture("hard")
    patches = build_detector_confidence_patch([source])
    assert len(patches) == len(source.evidence)
    for patch, original in zip(patches, source.evidence):
        assert patch["record_id"] == original.record_id
        assert patch["original_classification"] == original.classification
        assert patch["original_score"] == original.score
        assert patch["adjusted_score"] <= patch["original_score"]
        assert patch["mutation_rule"] == "source record retained; emit confidence patch only"


def test_determinism_bounded_scores_and_review_queue():
    source = fixture("soft")
    first = score_contradiction(source)
    second = score_contradiction(source)
    assert first == second
    assert 0.0 <= first.conflict_score <= 1.0
    assert 0.0 <= first.consistency_score <= 1.0
    queue = build_human_review_queue([source])
    assert len(queue) == 1
    assert queue[0]["priority"] == "MEDIUM"


def test_consistent_records_do_not_require_review():
    source = fixture("consistent")
    score = score_contradiction(source)
    assert score.review_required is False
    assert build_human_review_queue([source]) == []


def test_insufficient_evidence_is_retained_for_review():
    source = fixture("insufficient")
    ledger = build_contradiction_ledger([source])
    patches = build_detector_confidence_patch([source])
    queue = build_human_review_queue([source])
    assert len(ledger) == 1
    assert len(patches) == 1
    assert len(queue) == 1
    assert queue[0]["priority"] == "HIGH"
