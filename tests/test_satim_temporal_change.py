from copy import deepcopy

from satim_temporal_change import (
    ChangeType,
    EpochRecord,
    EvidenceLink,
    NO_CAUSAL_INFERENCE,
    ORIGINAL_EPOCH_RECORD_IMMUTABILITY,
    SEPARATE_BEFORE_AFTER_PROVENANCE,
    TemporalClass,
    TemporalObservation,
    VISIBLE_EPOCH_CHANGE_ONLY,
    build_detector_confidence_patch,
    build_human_review_queue,
    build_temporal_change_ledger,
    score_temporal_change,
    temporal_change_schema,
)


def epoch(role: str, classification: str = "PATCHWORK", score: float = 0.8) -> EpochRecord:
    return EpochRecord(
        record_id=f"{role}-001",
        epoch_id=f"EPOCH-{role}",
        capture_time="2026-01-01T12:00:00-04:00" if role == "BEFORE" else "2026-07-01T12:00:00-04:00",
        classification=classification,
        detector_score=score,
        geometry_id="GRID-001",
        map_scale=1.0,
        view_angle=0.0,
        provenance={"source": f"imagery-{role.lower()}", "epoch": role},
    )


def fixture(kind: str) -> TemporalObservation:
    signals = {
        "stable": {},
        "new": {ChangeType.NEW_FEATURE: 0.95},
        "removed": {ChangeType.REMOVED_FEATURE: 0.95},
        "expansion": {ChangeType.EXPANSION: 0.85},
        "contraction": {ChangeType.CONTRACTION: 0.8},
        "water_extent": {ChangeType.WATER_EXTENT_CHANGE: 0.85},
        "access_change": {ChangeType.ACCESS_CHANGE: 0.8},
        "artifact_driven": {ChangeType.SHAPE_CHANGE: 0.85},
        "insufficient_alignment": {ChangeType.SURFACE_COVER_CHANGE: 0.8},
    }
    kwargs = dict(
        comparison_id=f"TEMP-{kind.upper()}",
        before=epoch("BEFORE"),
        after=epoch("AFTER"),
        change_signals=signals[kind],
        links={item: True for item in EvidenceLink},
        spatial_overlap=0.95,
        registration_quality=0.95,
        scale_compatibility=0.95,
        view_angle_compatibility=0.95,
        artifact_confidence=0.1,
        contradiction_confidence=0.1,
        notes="Synthetic visible epoch change fixture.",
    )
    if kind == "artifact_driven":
        kwargs["artifact_confidence"] = 0.9
    if kind == "insufficient_alignment":
        kwargs["spatial_overlap"] = 0.3
        kwargs["registration_quality"] = 0.3
        kwargs["scale_compatibility"] = 0.4
        kwargs["view_angle_compatibility"] = 0.4
    return TemporalObservation(**kwargs)


def test_schema_contract_and_guardrails():
    schema = temporal_change_schema()
    assert schema["detector"] == "SATIM_TEMPORAL_SURFACE_CHANGE_DETECTOR_v1"
    assert set(schema["change_types"]) == {item.value for item in ChangeType}
    assert set(schema["classes"]) == {item.value for item in TemporalClass}
    assert set(schema["links"]) == {item.value for item in EvidenceLink}
    assert schema["guardrails"] == [
        VISIBLE_EPOCH_CHANGE_ONLY,
        ORIGINAL_EPOCH_RECORD_IMMUTABILITY,
        SEPARATE_BEFORE_AFTER_PROVENANCE,
        NO_CAUSAL_INFERENCE,
    ]
    assert "CAUSAL_INFERENCE" in schema["prohibited_outputs"]
    assert "SOURCE_RECORD_MUTATION" in schema["prohibited_outputs"]


def test_required_classifications_are_emitted():
    assert score_temporal_change(fixture("stable")).classification == "STABLE"
    assert score_temporal_change(fixture("new")).classification == "CONFIRMED_VISIBLE_CHANGE"
    assert score_temporal_change(fixture("expansion")).classification == "CONFIRMED_VISIBLE_CHANGE"
    assert score_temporal_change(fixture("artifact_driven")).classification == "ARTIFACT_DRIVEN_CHANGE"
    assert score_temporal_change(fixture("insufficient_alignment")).classification == "INSUFFICIENT_EPOCH_ALIGNMENT"


def test_all_required_change_types_are_supported():
    expected = {
        "new": "NEW_FEATURE",
        "removed": "REMOVED_FEATURE",
        "expansion": "EXPANSION",
        "contraction": "CONTRACTION",
        "water_extent": "WATER_EXTENT_CHANGE",
        "access_change": "ACCESS_CHANGE",
    }
    for kind, change_type in expected.items():
        assert change_type in score_temporal_change(fixture(kind)).change_types


def test_epoch_records_are_immutable_and_provenance_is_separate():
    source = fixture("new")
    before = deepcopy(source)
    ledger = build_temporal_change_ledger([source])[0]
    assert source == before
    assert ledger["before"]["record_id"] == source.before.record_id
    assert ledger["after"]["record_id"] == source.after.record_id
    assert ledger["before"]["provenance"] == source.before.provenance
    assert ledger["after"]["provenance"] == source.after.provenance
    assert ledger["before"]["provenance"] != ledger["after"]["provenance"]
    assert ORIGINAL_EPOCH_RECORD_IMMUTABILITY in ledger["guardrails"]
    assert SEPARATE_BEFORE_AFTER_PROVENANCE in ledger["guardrails"]


def test_scoring_is_deterministic_bounded_and_filtered():
    source = fixture("water_extent")
    first = score_temporal_change(source)
    second = score_temporal_change(source)
    assert first == second
    assert 0.0 <= first.change_score <= 1.0
    assert 0.0 <= first.alignment_score <= 1.0
    assert 0.0 <= first.adjusted_change_score <= 1.0
    artifact = score_temporal_change(fixture("artifact_driven"))
    assert artifact.adjusted_change_score < artifact.change_score


def test_confidence_patch_is_non_destructive():
    source = fixture("contraction")
    patches = build_detector_confidence_patch([source])
    assert len(patches) == 2
    for patch, record in zip(patches, (source.before, source.after)):
        assert patch["record_id"] == record.record_id
        assert patch["original_classification"] == record.classification
        assert patch["original_score"] == record.detector_score
        assert patch["mutation_rule"] == "original epoch record retained; emit temporal context patch only"


def test_review_queue_handles_artifacts_and_alignment_failure():
    queue = build_human_review_queue([
        fixture("artifact_driven"),
        fixture("insufficient_alignment"),
    ])
    assert len(queue) == 2
    assert queue[0]["classification"] == "ARTIFACT_DRIVEN_CHANGE"
    assert queue[1]["classification"] == "INSUFFICIENT_EPOCH_ALIGNMENT"
    assert queue[1]["priority"] == "HIGH"
    assert all(row["guardrail"] == NO_CAUSAL_INFERENCE for row in queue)


def test_links_are_evidentiary_only_and_preserved():
    ledger = build_temporal_change_ledger([fixture("access_change")])[0]
    assert ledger["linked_evidence"] == sorted(item.value for item in EvidenceLink)
    assert NO_CAUSAL_INFERENCE in ledger["guardrails"]
