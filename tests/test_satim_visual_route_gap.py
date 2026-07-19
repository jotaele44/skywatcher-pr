from satim_visual_route_gap import (
    GapClass,
    GapLink,
    GapObservation,
    PROXIMITY_ONLY_NO_ROUTE_RECONSTRUCTION,
    TrackPoint,
    UNKNOWN_GAP_GEOMETRY,
    build_human_review_queue,
    build_p_route_confidence_patch,
    build_visual_route_gap_ledger,
    score_gap_observation,
    visual_route_gap_schema,
)


def anchor(ts: str, lat: float, lon: float, heading: float = 90.0) -> TrackPoint:
    return TrackPoint(ts, lat, lon, altitude_ft=1200.0, speed_kt=90.0, heading_deg=heading)


def observation(kind: str) -> GapObservation:
    common = dict(
        gap_id=f"GAP-{kind}",
        source_id="FR24:synthetic",
        pre_gap_anchor=anchor("2026-06-09T12:00:00-04:00", 18.20, -66.30),
        post_gap_anchor=anchor("2026-06-09T12:04:00-04:00", 18.22, -66.27),
        observed_track_points=(
            anchor("2026-06-09T11:59:30-04:00", 18.19, -66.31),
            anchor("2026-06-09T12:04:30-04:00", 18.23, -66.26),
        ),
        screenshot_segment_id="SEG-001",
        screenshot_timestamp="2026-06-09T12:02:00-04:00",
        screenshot_georeferenced=True,
        links={
            GapLink.PATCHWORK_POI: True,
            GapLink.ROAD_END_NODE: True,
            GapLink.CUT_FILL_FEATURE: True,
            GapLink.LINEAR_CORRIDOR: True,
            GapLink.ARTIFACT_CONFIDENCE_PATCH: True,
        },
        flight_provenance={"source": "FR24", "mode": "observed_points_only"},
        visual_provenance={"source": "screenshot", "segment": "SEG-001"},
    )
    if kind == "compatible":
        return GapObservation(
            **common,
            gap_duration_score=0.9,
            endpoint_segment_proximity_score=0.95,
            temporal_alignment_score=0.9,
            heading_compatibility_score=0.85,
            altitude_speed_continuity_score=0.8,
            repeat_gridid_overlap_score=0.8,
            visual_feature_proximity_score=0.85,
            artifact_confidence=0.1,
        )
    if kind == "partial":
        return GapObservation(
            **common,
            gap_duration_score=0.65,
            endpoint_segment_proximity_score=0.65,
            temporal_alignment_score=0.6,
            heading_compatibility_score=0.55,
            altitude_speed_continuity_score=0.6,
            repeat_gridid_overlap_score=0.5,
            visual_feature_proximity_score=0.55,
            artifact_confidence=0.15,
        )
    if kind == "incompatible":
        return GapObservation(
            **common,
            gap_duration_score=0.2,
            endpoint_segment_proximity_score=0.1,
            temporal_alignment_score=0.2,
            heading_compatibility_score=0.1,
            altitude_speed_continuity_score=0.2,
            repeat_gridid_overlap_score=0.1,
            visual_feature_proximity_score=0.1,
            artifact_confidence=0.2,
        )
    return GapObservation(
        **{**common, "pre_gap_anchor": None, "screenshot_georeferenced": False, "screenshot_timestamp": ""},
        endpoint_segment_proximity_score=None,
        temporal_alignment_score=None,
        artifact_confidence=0.8,
    )


def test_schema_contract_and_guardrails():
    schema = visual_route_gap_schema()
    assert schema["joiner"] == "SATIM_FR24_VISUAL_ROUTE_GAP_JOINER_v1"
    assert schema["guardrail"] == PROXIMITY_ONLY_NO_ROUTE_RECONSTRUCTION
    assert schema["gap_geometry"] == UNKNOWN_GAP_GEOMETRY
    assert set(schema["classes"]) == {item.value for item in GapClass}
    assert "SYNTHETIC_GAP_POLYLINE" in schema["prohibited_outputs"]


def test_all_required_classes_are_emitted():
    assert score_gap_observation(observation("compatible")).classification == "GEOMETRICALLY_COMPATIBLE"
    assert score_gap_observation(observation("partial")).classification == "PARTIALLY_COMPATIBLE"
    assert score_gap_observation(observation("incompatible")).classification == "INCOMPATIBLE"
    assert score_gap_observation(observation("insufficient")).classification == "INSUFFICIENT_EVIDENCE"


def test_observed_track_immutability_and_no_gap_polyline():
    source = observation("compatible")
    before = source.observed_track_points
    row = build_visual_route_gap_ledger([source])[0]
    assert source.observed_track_points == before
    assert row["gap_geometry"] == UNKNOWN_GAP_GEOMETRY
    assert "gap_polyline" not in row
    assert row["pre_gap_anchor"]["timestamp"] == source.pre_gap_anchor.timestamp
    assert row["post_gap_anchor"]["timestamp"] == source.post_gap_anchor.timestamp


def test_provenance_remains_separate_and_deterministic():
    source = observation("compatible")
    first = build_visual_route_gap_ledger([source])
    second = build_visual_route_gap_ledger([source])
    assert first == second
    row = first[0]
    assert row["flight_provenance"] == source.flight_provenance
    assert row["visual_provenance"] == source.visual_provenance
    assert row["flight_provenance"] is not row["visual_provenance"]


def test_non_destructive_patch_and_review_queue():
    source = observation("insufficient")
    patch = build_p_route_confidence_patch([source])[0]
    assert patch["mutation_rule"] == "observed track retained; no gap polyline generated"
    assert patch["provenance_rule"] == "flight and visual provenance remain separate"
    queue = build_human_review_queue([source])
    assert len(queue) == 1
    assert queue[0]["priority"] == "HIGH"
    assert "MISSING_PRE_GAP_ANCHOR" in queue[0]["review_reasons"]
    assert "VISUAL_SEGMENT_NOT_GEOREFERENCED" in queue[0]["review_reasons"]


def test_scores_are_bounded_and_links_are_preserved():
    score = score_gap_observation(observation("compatible"))
    assert 0.0 <= score.raw_compatibility_score <= 1.0
    assert 0.0 <= score.final_compatibility_score <= 1.0
    assert set(score.linked_evidence) == {item.value for item in GapLink}
