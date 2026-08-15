from __future__ import annotations

import pytest

from skywatcher.satim.visual_reasoning_runtime import (
    ArtifactObservation,
    ExcavationObservation,
    LocationCandidate,
    MultiframeObservation,
    PalmObservation,
    ParameterSet,
    PortalObservation,
    QuarryObservation,
    RegisteredFeatureObservation,
    RegistrationMetrics,
    SceneEdge,
    SceneGraph,
    SceneNode,
    SeamObservation,
    ShadowObservation,
    VisualReasoningEngine,
    WaterObservation,
    ZoomObservation,
    assess_artifact,
    assess_excavation,
    assess_multiframe,
    assess_multiscale,
    assess_palm,
    assess_portal,
    assess_quarry,
    assess_seam,
    assess_shadow,
    assess_water,
    assess_zoom,
    locate_scene,
)


@pytest.fixture
def params() -> ParameterSet:
    return ParameterSet(
        {
            "ZOOM.EDGE_INFORMATION_MIN": 0.20,
            "ZOOM.TEXTURE_GAIN_MIN": 0.20,
            "ZOOM.RESAMPLING_DAMAGE_MAX": 0.60,
            "SHADOW.DARKNESS_RATIO_MIN": 0.20,
            "SHADOW.DARKNESS_RATIO_MAX": 0.75,
            "SHADOW.LOCAL_DEVIATION_MAX": 0.20,
            "SHADOW.TEXTURE_RETENTION_MIN": 0.40,
            "SHADOW.DIRECTION_TOLERANCE_DEG": 20.0,
            "SHADOW.CLIPPED_BLACK_RATIO": 0.90,
            "SEAM.LINEARITY_MIN": 0.70,
            "SEAM.BOUNDARY_LENGTH_MIN_PX": 20.0,
            "SEAM.LUMINANCE_DELTA_MIN": 0.20,
            "SEAM.COLOR_DELTA_MIN": 0.20,
            "SEAM.HISTOGRAM_DISTANCE_MIN": 0.20,
            "SEAM.SHARPNESS_DELTA_MIN": 0.20,
            "SEAM.TEXTURE_DELTA_MIN": 0.20,
            "SEAM.NOISE_DELTA_MIN": 0.20,
            "SEAM.COMPRESSION_DELTA_MIN": 0.20,
            "SEAM.REGISTRATION_OFFSET_MIN_PX": 2.0,
            "SEAM.SCORE_LOW": 0.25,
            "SEAM.SCORE_MODERATE": 0.50,
            "SEAM.SCORE_HIGH": 0.75,
            "ARTIFACT.RENDER_SCALE_DEPENDENCY_MIN": 0.70,
            "ARTIFACT.MULTISCALE_PERSISTENCE_MIN": 0.65,
            "ARTIFACT.MULTIFRAME_PERSISTENCE_MIN": 0.65,
            "ARTIFACT.REAL_OBJECT_PROMOTION_MIN": 0.70,
            "ARTIFACT.ARTIFACT_PROMOTION_MIN": 0.70,
            "ARTIFACT.MIXED_STATE_MARGIN": 0.12,
            "PALM.RADIALITY_MIN": 0.65,
            "PALM.FROND_COUNT_MIN": 5.0,
            "PALM.CROWN_CIRCULARITY_MIN": 0.35,
            "PALM.CROWN_CIRCULARITY_MAX": 0.90,
            "PALM.TRUNK_SUPPORT_WEIGHT": 0.20,
            "PALM.SHADOW_SUPPORT_WEIGHT": 0.20,
            "PALM.MULTISCALE_SUPPORT_WEIGHT": 0.40,
            "PALM.CANDIDATE_MIN": 0.55,
            "PALM.SUPPORTED_MIN": 0.70,
            "WATER.TEXTURE_MAX": 0.45,
            "WATER.SPECULAR_SUPPORT_MIN": 0.40,
            "WATER.BANK_EDGE_MIN": 0.55,
            "WATER.CHANNEL_CONTINUITY_MIN": 0.60,
            "WATER.RIPARIAN_SUPPORT_MIN": 0.40,
            "WATER.MEANDER_SUPPORT_MIN": 0.30,
            "WATER.SHADOW_CONFLICT_MAX": 0.50,
            "WATER.CANDIDATE_MIN": 0.50,
            "WATER.SUPPORTED_MIN": 0.65,
            "HYDRO.CHANNEL_ELONGATION_MIN": 0.70,
            "HYDRO.BANK_PARALLELISM_MIN": 0.55,
            "HYDRO.CLOSED_SHORELINE_MIN": 0.80,
            "HYDRO.CANAL_LINEARITY_MIN": 0.85,
            "QUARRY.EXPOSED_GROUND_MIN": 0.55,
            "QUARRY.BENCH_COUNT_MIN": 2.0,
            "QUARRY.BENCH_PARALLELISM_MIN": 0.55,
            "QUARRY.PIT_CONCAVITY_MIN": 0.45,
            "QUARRY.HIGHWALL_SUPPORT_MIN": 0.50,
            "QUARRY.HAUL_ROAD_SUPPORT_MIN": 0.45,
            "QUARRY.STOCKPILE_SUPPORT_MIN": 0.40,
            "QUARRY.PROCESSING_CONTEXT_MIN": 0.40,
            "QUARRY.SEDIMENT_CONTROL_MIN": 0.30,
            "QUARRY.CANDIDATE_MIN": 0.55,
            "QUARRY.SUPPORTED_MIN": 0.70,
            "QUARRY.NATURAL_SCARP_NEGATIVE_WEIGHT": 0.60,
            "QUARRY.LANDSLIDE_NEGATIVE_WEIGHT": 0.60,
            "QUARRY.ROAD_CUT_NEGATIVE_WEIGHT": 0.50,
            "QUARRY.KARST_NEGATIVE_WEIGHT": 0.50,
            "QUARRY.CONSTRUCTION_NEGATIVE_WEIGHT": 0.50,
            "EXCAVATION.FRESH_SOIL_MIN": 0.55,
            "EXCAVATION.VEGETATION_REMOVAL_MIN": 0.55,
            "EXCAVATION.CUT_GEOMETRY_MIN": 0.55,
            "EXCAVATION.SPOIL_ADJACENCY_MIN": 0.50,
            "EXCAVATION.VISIBLE_WALL_MIN": 0.50,
            "EXCAVATION.TEMPORARY_ACCESS_SUPPORT_MIN": 0.45,
            "EXCAVATION.DEPTH_CONFIDENCE_MIN": 0.70,
            "PORTAL.OPENING_GEOMETRY_MIN": 0.65,
            "PORTAL.STRUCTURAL_EDGE_MIN": 0.55,
            "PORTAL.SLOPE_RELATION_MIN": 0.55,
            "PORTAL.ACCESS_RELATION_MIN": 0.45,
            "PORTAL.MULTISCALE_PERSISTENCE_MIN": 0.60,
            "PORTAL.CULVERT_CONFLICT_WEIGHT": 0.60,
            "PORTAL.TREE_SHADOW_CONFLICT_WEIGHT": 0.60,
            "PORTAL.BRIDGE_SHADOW_CONFLICT_WEIGHT": 0.60,
            "PORTAL.ROCK_OVERHANG_CONFLICT_WEIGHT": 0.50,
            "PORTAL.ARTIFACT_CONFLICT_WEIGHT": 0.80,
            "MULTISCALE.FRAME_REGISTRATION_MIN": 0.70,
            "MULTISCALE.GEOMETRIC_PERSISTENCE_MIN": 0.65,
            "MULTISCALE.CLASS_STABILITY_MIN": 0.65,
            "MULTISCALE.RESOLUTION_LOSS_TOLERANCE": 0.70,
            "MULTIFRAME.MIN_SHARED_FEATURES": 3.0,
            "MULTIFRAME.REGISTRATION_MAX_ERROR_PX": 3.0,
            "MULTIFRAME.FEATURE_CONSENSUS_MIN": 0.70,
            "SCENE.RELATION_CONFIDENCE_MIN": 0.60,
            "LOCATOR.TEXT_WEIGHT": 0.16,
            "LOCATOR.ROAD_GRAPH_WEIGHT": 0.20,
            "LOCATOR.HYDROGRAPHY_WEIGHT": 0.16,
            "LOCATOR.TERRAIN_WEIGHT": 0.10,
            "LOCATOR.BUILDING_WEIGHT": 0.10,
            "LOCATOR.LANDMARK_WEIGHT": 0.10,
            "LOCATOR.VEGETATION_WEIGHT": 0.04,
            "LOCATOR.MULTIFRAME_WEIGHT": 0.10,
            "LOCATOR.GENERIC_SIMILARITY_WEIGHT": 0.04,
            "LOCATOR.HARD_CONTRADICTION_PENALTY": 1.0,
            "LOCATOR.SOFT_CONTRADICTION_PENALTY": 0.08,
            "LOCATOR.MIN_CANDIDATES_PRESERVED": 2.0,
            "LOCATOR.MAX_CANDIDATES_PRESERVED": 5.0,
            "LOCATOR.RUNNER_UP_MARGIN_MIN": 0.08,
            "LOCATOR.L1_THRESHOLD": 0.20,
            "LOCATOR.L2_THRESHOLD": 0.35,
            "LOCATOR.L3_THRESHOLD": 0.50,
            "LOCATOR.L4_THRESHOLD": 0.62,
            "LOCATOR.L5_THRESHOLD": 0.72,
            "LOCATOR.L6_THRESHOLD": 0.82,
            "LOCATOR.L7_THRESHOLD": 0.92,
            "LOCATOR.EXACT_MIN_CONTROL_POINTS": 4.0,
            "LOCATOR.EXACT_MAX_RMSE_PX": 2.0,
            "LOCATOR.EXACT_MAX_RMSE_M": 5.0,
            "LOCATOR.EXACT_MAX_ERROR_RADIUS_M": 15.0,
            "LOCATOR.LEAVE_ONE_OUT_MAX_RESIDUAL": 3.0,
        }
    )


def test_missing_parameters_fail_closed() -> None:
    result = assess_zoom(ZoomObservation(0.1, 0.1, 0.9), ParameterSet({}))
    assert result.state == "UNRESOLVED"
    assert "RC_MISSING_NOT_NEGATIVE" in result.reason_codes


def test_overzoom_cannot_gain_detail_confidence(params: ParameterSet) -> None:
    result = assess_zoom(ZoomObservation(0.05, 0.03, 0.90), params)
    assert result.state == "OVERZOOMED"
    assert "RC_OVERZOOM_NO_NEW_EVIDENCE" in result.reason_codes


def test_shadow_requires_local_field_and_geometry(params: ParameterSet) -> None:
    result = assess_shadow(ShadowObservation(0.45, 0.05, 0.75, 0.85, 5.0, 0.01, True), params)
    assert result.state == "PHYSICALLY_PLAUSIBLE_SHADOW"
    assert result.reason_codes == ("RC_SHADOW_CONSISTENT",)


def test_dark_region_alone_does_not_become_shadow(params: ParameterSet) -> None:
    result = assess_shadow(ShadowObservation(0.45, 0.05, 0.75, 0.85, 5.0, 0.01, False), params)
    assert result.state != "PHYSICALLY_PLAUSIBLE_SHADOW"


def test_clipped_black_is_explicit_state(params: ParameterSet) -> None:
    result = assess_shadow(ShadowObservation(0.10, 0.9, 0.0, 0.0, 90.0, 0.95, False), params)
    assert result.state == "CLIPPED_BLACK"


def test_seam_with_real_feature_continuity_is_not_split(params: ParameterSet) -> None:
    result = assess_seam(
        SeamObservation(0.95, 500, 0.4, 0.4, 0.5, 0.4, 0.4, 0.4, 0.4, 3.0, feature_continues=True),
        params,
    )
    assert result.state == "CONTINUOUS_WITH_IMAGE_DISCREPANCY"
    assert "RC_SEAM_NOT_REAL_WORLD_BOUNDARY" in result.reason_codes
    assert "RC_CROSS_SEAM_CONTINUITY" in result.reason_codes


def test_stitch_ghost_is_artifact_candidate(params: ParameterSet) -> None:
    result = assess_seam(
        SeamObservation(0.95, 500, 0.4, 0.4, 0.5, 0.4, 0.4, 0.4, 0.4, 3.0, duplicate_or_ghost=True),
        params,
    )
    assert result.state == "STITCHING_ARTIFACT_CANDIDATE"
    assert "RC_STITCHING_GHOST" in result.reason_codes


def test_render_scale_dependent_feature_is_not_locator_landmark(params: ParameterSet) -> None:
    result = assess_artifact(ArtifactObservation(0.95, 0.1, 0.1, 0.2, 0.2, 0.2, 0.9, 0.9), params)
    assert result.state == "RENDERING_ARTIFACT_CANDIDATE"
    assert "RC_ARTIFACT_EXCLUDED_FROM_LOCATOR" in result.reason_codes


def test_persistent_coherent_feature_can_be_real_object_candidate(params: ParameterSet) -> None:
    result = assess_artifact(ArtifactObservation(0.05, 0.9, 0.9, 0.9, 0.9, 0.9, 0.05, 0.05), params)
    assert result.state == "REAL_WORLD_OBJECT_CANDIDATE"


def test_palm_species_remains_unresolved_without_species_evidence(params: ParameterSet) -> None:
    result = assess_palm(PalmObservation(0.9, 8, 0.7, 0.8, 0.8, 0.9), params)
    assert result.state == "PALM_TREE"
    assert result.metadata["species_state"] == "UNRESOLVED"
    assert "RC_PALM_SPECIES_UNRESOLVED" in result.reason_codes


def test_dark_surface_without_hydro_geometry_does_not_become_water(params: ParameterSet) -> None:
    result = assess_water(WaterObservation(0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.1, 0.0, 0.0, 0.0, 0.0), params)
    assert result.state == "UNRESOLVED"
    assert "RC_DARKNESS_INSUFFICIENT_FOR_WATER" in result.reason_codes


def test_connected_banked_water_classifies_river_or_stream(params: ParameterSet) -> None:
    result = assess_water(WaterObservation(0.2, 0.6, 0.9, 0.95, 0.9, 0.8, 0.1, 0.95, 0.9, 0.1, 0.2), params)
    assert result.state == "RIVER_OR_STREAM"
    assert "RC_HYDRO_CHANNEL_FORM" in result.reason_codes


def test_closed_water_geometry_classifies_closed_form(params: ParameterSet) -> None:
    result = assess_water(WaterObservation(0.2, 0.8, 0.9, 0.8, 0.6, 0.4, 0.1, 0.4, 0.6, 0.95, 0.2), params)
    assert result.state == "LAKE_POND_OR_RESERVOIR"


def test_bare_ground_alone_is_not_quarry(params: ParameterSet) -> None:
    result = assess_quarry(QuarryObservation(0.9, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), params)
    assert result.state == "GROUND_DISTURBANCE_UNRESOLVED"
    assert "RC_BARE_GROUND_NOT_QUARRY" in result.reason_codes


def test_visual_quarry_never_implies_legal_identity(params: ParameterSet) -> None:
    result = assess_quarry(QuarryObservation(0.9, 5, 0.9, 0.9, 0.9, 0.9, 0.8, 0.9, 0.8), params)
    assert result.state in {"QUARRY_CANDIDATE", "QUARRY_SUPPORTED"}
    assert result.metadata["legal_identity"] is False
    assert "RC_VISUAL_QUARRY_NOT_LEGAL_IDENTITY" in result.reason_codes


def test_excavation_depth_requires_geometry(params: ParameterSet) -> None:
    result = assess_excavation(ExcavationObservation(0.9, 0.9, 0.9, 0.9, 0.9, 0.9, None), params)
    assert result.state == "EXCAVATION_CANDIDATE"
    assert result.metadata["depth_state"] == "UNRESOLVED"
    assert "RC_DEPTH_REQUIRES_GEOMETRY" in result.reason_codes


def test_portal_like_does_not_establish_subsurface_identity(params: ParameterSet) -> None:
    result = assess_portal(PortalObservation(0.9, 0.9, 0.9, 0.9, 0.9), params)
    assert result.state == "PORTAL_LIKE_FEATURE"
    assert result.metadata["subsurface_identity"] is False
    assert "RC_PORTAL_NOT_UNDERGROUND_IDENTITY" in result.reason_codes


def test_multiscale_resolution_loss_is_not_absence(params: ParameterSet) -> None:
    result = assess_multiscale(RegisteredFeatureObservation(0.9, 0.2, 0.3, 0.95), params)
    assert result.state == "BELOW_RESOLUTION_NOT_ABSENT"


def test_multiframe_consensus_requires_registration(params: ParameterSet) -> None:
    good = assess_multiframe(MultiframeObservation(5, 1.0, 0.9), params)
    bad = assess_multiframe(MultiframeObservation(5, 9.0, 0.9), params)
    assert good.state == "MULTIFRAME_SUPPORTED"
    assert bad.state == "UNRESOLVED"


def test_scene_relationship_support_does_not_promote_identity(params: ParameterSet) -> None:
    graph = SceneGraph()
    graph.add_node(SceneNode("road", "ROAD", 0.9, ("f1",)))
    graph.add_node(SceneNode("water", "RIVER_OR_STREAM", 0.9, ("f1", "f2")))
    result = graph.add_relation(SceneEdge("road", "water", "crosses", 0.9), params)
    assert result.state == "RELATION_SUPPORTED_IDENTITY_UNRESOLVED"
    assert graph.edges[0].relation == "crosses"


def _strong_candidate(candidate_id: str, score: float = 0.95) -> LocationCandidate:
    return LocationCandidate(
        candidate_id,
        text_score=score,
        road_score=score,
        hydro_score=score,
        terrain_score=score,
        building_score=score,
        landmark_score=score,
        vegetation_score=score,
        multiframe_score=score,
        generic_similarity_score=score,
        text_cue_count=2,
        independent_topology_support=True,
    )


def test_one_label_never_certifies_exact_location(params: ParameterSet) -> None:
    candidate = LocationCandidate(
        "same-name-road",
        text_score=1.0,
        road_score=0.95,
        hydro_score=0.95,
        terrain_score=0.95,
        building_score=0.95,
        landmark_score=0.95,
        vegetation_score=0.95,
        multiframe_score=0.95,
        generic_similarity_score=0.95,
        text_cue_count=1,
        independent_topology_support=False,
    )
    result = locate_scene([candidate], params)
    assert result.state == "MULTIPLE_CANDIDATES"
    assert "RC_ONE_LABEL_NOT_EXACT" in result.reason_codes


def test_locator_preserves_runner_up_and_ties_fail_closed(params: ParameterSet) -> None:
    result = locate_scene([_strong_candidate("A", 0.90), _strong_candidate("B", 0.88)], params)
    assert result.state == "MULTIPLE_CANDIDATES"
    assert result.best_candidate == "A"
    assert result.second_candidate == "B"
    assert "RC_LOCATION_TIE" in result.reason_codes


def test_hard_geometric_contradiction_rejects_candidate(params: ParameterSet) -> None:
    bad = _strong_candidate("bad")
    bad = LocationCandidate(**{**bad.__dict__, "hard_geometric_contradiction": True})
    good = _strong_candidate("good", 0.85)
    result = locate_scene([bad, good], params)
    assert "bad" in result.rejected_candidates
    assert result.best_candidate == "good"


def test_exact_location_requires_registration_gates(params: ParameterSet) -> None:
    result = locate_scene([_strong_candidate("A", 0.95)], params)
    assert result.state == "EXACT_PROVISIONAL"
    assert result.location_level == 6
    assert "RC_EXACT_PROVISIONAL" in result.reason_codes


def test_exact_location_certification_reports_error_radius(params: ParameterSet) -> None:
    registration = RegistrationMetrics(6, 0.8, 1.5, 5.0, 1.0)
    result = locate_scene([_strong_candidate("A", 0.95)], params, registration)
    assert result.state == "EXACT_CERTIFIED"
    assert result.location_level == 7
    assert result.error_radius_m == 5.0
    assert "RC_EXACT_CERTIFIED" in result.reason_codes
    assert "RC_LOCATION_ERROR_RADIUS_REQUIRED" in result.reason_codes


def test_artifact_landmark_blocks_exact_promotion(params: ParameterSet) -> None:
    candidate = _strong_candidate("A")
    candidate = LocationCandidate(**{**candidate.__dict__, "artifact_landmark_used": True})
    result = locate_scene([candidate], params, RegistrationMetrics(6, 0.5, 1.0, 3.0, 1.0))
    assert result.state == "UNRESOLVED"
    assert "RC_ARTIFACT_EXCLUDED_FROM_LOCATOR" in result.reason_codes


def test_engine_binds_one_explicit_parameter_set(params: ParameterSet) -> None:
    engine = VisualReasoningEngine(params.values)
    result = engine.shadow(ShadowObservation(0.45, 0.05, 0.75, 0.85, 5.0, 0.01, True))
    assert result.state == "PHYSICALLY_PLAUSIBLE_SHADOW"
