from satim_linear_corridor import (
    CorridorClass,
    CorridorLink,
    CorridorObservation,
    CorridorSignal,
    NON_DESTRUCTIVE_ARTIFACT_FILTER,
    VISIBLE_LINEAR_FEATURE_ONLY,
    build_linear_corridor_ledger,
    build_p_route_confidence_patch,
    linear_corridor_schema,
    score_corridor_observation,
)


def corridor_fixture() -> CorridorObservation:
    return CorridorObservation(
        corridor_id="SATIM-LINEAR-PR771-001",
        grid_id="PR-BARRANQUITAS-PR771-RIO_GRANDE_DE_MANATI",
        source_id="SATIM_ARTIFACT_FILTER_LEDGER:SATIM-ARTIFACT-PR771-001",
        timestamp_local="2026-06-29T15:00:00-04:00",
        signals={
            CorridorSignal.VEGETATION_BREAK: 1.0,
            CorridorSignal.UNPAVED_LINEAR_CLEARING: 0.8,
            CorridorSignal.UTILITY_EASEMENT: 0.2,
            CorridorSignal.SERVICE_TRACK: 1.0,
            CorridorSignal.DRAINAGE_CORRIDOR: 0.1,
            CorridorSignal.FENCE_OR_BOUNDARY_STRIP: 0.1,
            CorridorSignal.CONTINUITY: 0.9,
            CorridorSignal.LINEARITY: 0.95,
            CorridorSignal.WIDTH_CONSISTENCY: 0.8,
            CorridorSignal.EDGE_DEFINITION: 0.8,
            CorridorSignal.VEGETATION_CONTRAST: 0.9,
            CorridorSignal.SURFACE_CONTRAST: 0.8,
            CorridorSignal.JUNCTION_OR_TERMINUS_EVIDENCE: 0.8,
            CorridorSignal.VISIBLE_ASSET_SUPPORT: 0.5,
            CorridorSignal.RECURRENCE: 1.0,
        },
        classes=(CorridorClass.ACCESS_CORRIDOR,),
        links={
            CorridorLink.PATCHWORK_POI: True,
            CorridorLink.ROAD_END_NODE: True,
            CorridorLink.CUT_FILL_FEATURE: True,
            CorridorLink.REPEAT_GRIDID: True,
        },
        patchwork_poi_id="SATIM-PR771-BARRANQUITAS-001",
        road_end_node_id="SATIM-ROAD-END-PR771-001",
        cut_fill_feature_id="SATIM-CUT-FILL-PR771-001",
        repeat_grid_id="PR-BARRANQUITAS-PR771-RIO_GRANDE_DE_MANATI",
        artifact_confidence=0.4,
        notes="Synthetic regression fixture; visible surface evidence only.",
    )


def test_schema_has_required_contract_and_guardrails():
    schema = linear_corridor_schema()

    assert schema["detector"] == "SATIM_LINEAR_CLEARING_CORRIDOR_DETECTOR_v1"
    assert schema["guardrail"] == VISIBLE_LINEAR_FEATURE_ONLY
    assert schema["artifact_filter"] == NON_DESTRUCTIVE_ARTIFACT_FILTER
    for signal in (
        "VEGETATION_BREAK",
        "UNPAVED_LINEAR_CLEARING",
        "UTILITY_EASEMENT",
        "SERVICE_TRACK",
        "DRAINAGE_CORRIDOR",
        "FENCE_OR_BOUNDARY_STRIP",
    ):
        assert signal in schema["signals"]
    assert set(schema["signal_weights"]) == set(schema["signals"])
    assert "UNKNOWN_LINEAR_CLEARING" in schema["classes"]
    assert set(schema["links"]) == {
        "PATCHWORK_POI",
        "ROAD_END_NODE",
        "CUT_FILL_FEATURE",
        "REPEAT_GRIDID",
    }


def test_fixture_score_is_deterministic_and_artifact_patch_is_non_destructive():
    first = score_corridor_observation(corridor_fixture())
    second = score_corridor_observation(corridor_fixture())

    assert first == second
    assert first.original_corridor_score == 0.779
    assert first.linkage_score == 0.17
    assert first.pre_filter_score == 0.949
    assert first.artifact_confidence == 0.4
    assert first.adjusted_corridor_score == 0.7592
    assert first.confidence_band == "HIGH"
    assert first.guardrail == VISIBLE_LINEAR_FEATURE_ONLY
    assert first.artifact_filter_status == NON_DESTRUCTIVE_ARTIFACT_FILTER
    assert first.classes == ("ACCESS_CORRIDOR",)


def test_ledger_preserves_scores_links_and_provenance():
    rows = build_linear_corridor_ledger([corridor_fixture()])

    assert len(rows) == 1
    row = rows[0]
    assert row["corridor_id"] == "SATIM-LINEAR-PR771-001"
    assert row["original_corridor_score"] == 0.779
    assert row["pre_filter_score"] == 0.949
    assert row["adjusted_corridor_score"] == 0.7592
    assert row["guardrail"] == VISIBLE_LINEAR_FEATURE_ONLY
    assert row["linked_evidence"] == [
        "CUT_FILL_FEATURE",
        "PATCHWORK_POI",
        "REPEAT_GRIDID",
        "ROAD_END_NODE",
    ]
    assert row["road_end_node_id"] == "SATIM-ROAD-END-PR771-001"
    assert row["signal_contributions"]["LINEARITY"] == 0.114


def test_p_route_patch_retains_candidate_and_separable_scores():
    rows = build_p_route_confidence_patch([corridor_fixture()])

    assert len(rows) == 1
    row = rows[0]
    assert row["patch_status"] == "P_ROUTE_CONFIDENCE_PATCH"
    assert row["original_corridor_score"] == 0.779
    assert row["artifact_confidence"] == 0.4
    assert row["adjusted_corridor_score"] == 0.7592
    assert row["mutation_rule"] == "corridor candidate retained; artifact adjustment is advisory only"
    assert row["provenance_rule"] == "original, linkage, artifact, and adjusted scores remain separable"


def test_missing_optional_links_remain_valid_and_unknown_class_is_safe_default():
    observation = CorridorObservation(
        corridor_id="SATIM-LINEAR-UNKNOWN-001",
        grid_id="GRID-UNKNOWN",
        source_id="synthetic",
        signals={CorridorSignal.LINEARITY: 0.5, CorridorSignal.CONTINUITY: 0.4},
    )
    score = score_corridor_observation(observation)

    assert score.classes == ("UNKNOWN_LINEAR_CLEARING",)
    assert score.linkage_score == 0.0
    assert score.linked_evidence == ()
    assert score.guardrail == VISIBLE_LINEAR_FEATURE_ONLY
