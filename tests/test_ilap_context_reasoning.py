import pytest

from skywatcher.satim.ilap_context_reasoning import (
    AnnotationRecord,
    ComparisonSet,
    SourceRef,
    assess_visibility,
    build_explainability_packet,
    contextual_percentile,
    independent_source_count,
    normalize_candidate_families,
    validate_annotation,
    validate_instance_relation_state,
    validate_negative_observation_state,
)


def test_no_comparison_population_means_no_anomaly_percentile() -> None:
    result = contextual_percentile(24, None)
    assert result["state"] == "ABSTAIN_INSUFFICIENT_EVIDENCE"
    assert result["percentile"] is None


def test_contextual_percentile_is_descriptive_only() -> None:
    comparison = ComparisonSet(
        comparison_set_id="rural-compounds-v1",
        values=(1, 2, 3, 4, 5),
        selection_rule="frozen control set",
    )
    result = contextual_percentile(4, comparison)
    assert result["state"] == "DESCRIPTIVE_BASELINE_ONLY"
    assert result["comparison_n"] == 5
    assert result["percentile"] == 80.0


def test_derived_images_do_not_increase_independent_source_count() -> None:
    sources = [
        SourceRef("a", provider="P1", lineage_id="L1"),
        SourceRef("b", provider="P1", lineage_id="L1", derived_from="a"),
        SourceRef("c", provider="P2", lineage_id="L2"),
    ]
    assert independent_source_count(sources) == 2


def test_visibility_preserves_measurement_without_inventing_category() -> None:
    result = assess_visibility(0.42, canopy=0.38, shadow=0.1)
    assert result.visible_ground_fraction == 0.42
    assert result.state == "UNKNOWN_EXTENT"


def test_visibility_fraction_outside_unit_interval_fails_closed() -> None:
    with pytest.raises(ValueError):
        assess_visibility(1.2)


def test_negative_observation_distinguishes_occluded_from_absent() -> None:
    assert validate_negative_observation_state("NOT_VISIBLE_OCCLUDED") == "NOT_VISIBLE_OCCLUDED"
    assert validate_negative_observation_state("OBSERVED_ABSENT") == "OBSERVED_ABSENT"
    assert "NOT_VISIBLE_OCCLUDED" != "OBSERVED_ABSENT"


def test_persistent_instance_relation_requires_supported_state() -> None:
    assert validate_instance_relation_state("POSSIBLE_SAME_OBJECT") == "POSSIBLE_SAME_OBJECT"
    with pytest.raises(ValueError):
        validate_instance_relation_state("NEAREST_OBJECT")


def test_human_annotation_remains_provenance_record_not_ground_truth() -> None:
    record = AnnotationRecord(
        annotation_id="ann-1",
        source_frame_id="frame-1",
        revision=1,
        actor_type="HUMAN",
        class_name="PALM_LIKE_CROWN",
        coordinate_space="RAW_PIXEL",
        evidence_state="CANDIDATE",
        ui_color="GREEN",
    )
    assert validate_annotation(record) == record
    assert record.actor_type == "HUMAN"


def test_candidate_family_registry_rejects_hidden_purpose_labels() -> None:
    families = normalize_candidate_families([
        "ILAP_VISUAL_LAYOUT_CANDIDATE",
        "ILAP_ACCESSIBILITY_CANDIDATE",
    ])
    assert len(families) == 2
    with pytest.raises(ValueError):
        normalize_candidate_families(["HIDDEN_INFRASTRUCTURE_CONFIRMED"])


def test_explainability_packet_preserves_contradictions_and_falsifiers() -> None:
    packet = build_explainability_packet(
        why_flagged=["road terminates at compound"],
        observed=["two blue-roof candidates"],
        not_observed=["no visible large parking area"],
        unknown=["vehicle count unresolved"],
        supporting_evidence=["managed parcel morphology"],
        contradicting_evidence=["direct road access lowers access-friction hypothesis"],
        falsifiers_remaining=["local controls show layout is common"],
        next_data_needed=["registered comparison set"],
        comparison_set_id=None,
        sources=[SourceRef("frame-1", provider="P1", lineage_id="L1")],
        candidate_families=["ILAP_VISUAL_LAYOUT_CANDIDATE"],
    )
    assert packet.contradicting_evidence
    assert packet.falsifiers_remaining
    assert packet.comparison_set_id is None
