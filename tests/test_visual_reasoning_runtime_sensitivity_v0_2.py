from __future__ import annotations

from copy import deepcopy

from skywatcher.satim.visual_reasoning_runtime import (
    ArtifactObservation,
    LocationCandidate,
    ParameterSet,
    PalmObservation,
    QuarryObservation,
    RegistrationMetrics,
    SeamObservation,
    ShadowObservation,
    WaterObservation,
    ZoomObservation,
    assess_artifact,
    assess_palm,
    assess_quarry,
    assess_seam,
    assess_shadow,
    assess_water,
    assess_zoom,
    locate_scene,
)


def test_zoom_damage_boundary_flips_only_at_registered_threshold() -> None:
    parameters = ParameterSet(
        {
            "ZOOM.EDGE_INFORMATION_MIN": 0.2,
            "ZOOM.TEXTURE_GAIN_MIN": 0.2,
            "ZOOM.RESAMPLING_DAMAGE_MAX": 0.6,
        }
    )
    below = assess_zoom(ZoomObservation(0.1, 0.1, 0.6), parameters)
    above = assess_zoom(ZoomObservation(0.1, 0.1, 0.6001), parameters)
    assert below.state == "DETAIL_USABLE"
    assert above.state == "OVERZOOMED"


def test_shadow_darkness_boundary_is_parameter_controlled() -> None:
    parameters = ParameterSet(
        {
            "SHADOW.DARKNESS_RATIO_MIN": 0.2,
            "SHADOW.DARKNESS_RATIO_MAX": 0.75,
            "SHADOW.LOCAL_DEVIATION_MAX": 0.2,
            "SHADOW.TEXTURE_RETENTION_MIN": 0.4,
            "SHADOW.DIRECTION_TOLERANCE_DEG": 20.0,
            "SHADOW.CLIPPED_BLACK_RATIO": 0.9,
        }
    )
    at_boundary = assess_shadow(
        ShadowObservation(0.2, 0.1, 0.8, 0.8, 5.0, 0.0, True),
        parameters,
    )
    outside = assess_shadow(
        ShadowObservation(0.1999, 0.1, 0.8, 0.8, 5.0, 0.0, True),
        parameters,
    )
    assert at_boundary.state == "PHYSICALLY_PLAUSIBLE_SHADOW"
    assert outside.state == "UNRESOLVED"


def test_seam_severity_is_parameter_controlled() -> None:
    parameters = ParameterSet(
        {
            "SEAM.LINEARITY_MIN": 0.7,
            "SEAM.BOUNDARY_LENGTH_MIN_PX": 20.0,
            "SEAM.LUMINANCE_DELTA_MIN": 0.2,
            "SEAM.COLOR_DELTA_MIN": 0.2,
            "SEAM.HISTOGRAM_DISTANCE_MIN": 0.2,
            "SEAM.SHARPNESS_DELTA_MIN": 0.2,
            "SEAM.TEXTURE_DELTA_MIN": 0.2,
            "SEAM.NOISE_DELTA_MIN": 0.2,
            "SEAM.COMPRESSION_DELTA_MIN": 0.2,
            "SEAM.REGISTRATION_OFFSET_MIN_PX": 2.0,
            "SEAM.SCORE_LOW": 0.25,
            "SEAM.SCORE_MODERATE": 0.5,
            "SEAM.SCORE_HIGH": 0.75,
        }
    )
    observation = SeamObservation(
        0.9,
        100,
        0.3,
        0.3,
        0.3,
        0.3,
        0.1,
        0.1,
        0.1,
        0.0,
    )
    result = assess_seam(observation, parameters)
    assert result.state == "SEAM_CANDIDATE"
    assert result.metadata["severity"] == "MODERATE"


def test_artifact_real_promotion_boundary_uses_registry_value() -> None:
    base = {
        "ARTIFACT.RENDER_SCALE_DEPENDENCY_MIN": 0.7,
        "ARTIFACT.MULTISCALE_PERSISTENCE_MIN": 0.65,
        "ARTIFACT.MULTIFRAME_PERSISTENCE_MIN": 0.65,
        "ARTIFACT.REAL_OBJECT_PROMOTION_MIN": 0.7,
        "ARTIFACT.ARTIFACT_PROMOTION_MIN": 0.7,
        "ARTIFACT.MIXED_STATE_MARGIN": 0.1,
    }
    observation = ArtifactObservation(0.0, 0.8, 0.8, 0.8, 0.8, 0.8, 0.0, 0.0)
    supported = assess_artifact(observation, ParameterSet(base))
    tightened = deepcopy(base)
    tightened["ARTIFACT.REAL_OBJECT_PROMOTION_MIN"] = 0.9
    unresolved = assess_artifact(observation, ParameterSet(tightened))
    assert supported.state == "REAL_WORLD_OBJECT_CANDIDATE"
    assert unresolved.state == "AMBIGUOUS"


def test_palm_radiality_threshold_is_sensitivity_visible() -> None:
    base = {
        "PALM.RADIALITY_MIN": 0.65,
        "PALM.FROND_COUNT_MIN": 5.0,
        "PALM.CROWN_CIRCULARITY_MIN": 0.35,
        "PALM.CROWN_CIRCULARITY_MAX": 0.9,
        "PALM.TRUNK_SUPPORT_WEIGHT": 0.2,
        "PALM.SHADOW_SUPPORT_WEIGHT": 0.2,
        "PALM.MULTISCALE_SUPPORT_WEIGHT": 0.4,
        "PALM.CANDIDATE_MIN": 0.55,
        "PALM.SUPPORTED_MIN": 0.7,
    }
    observation = PalmObservation(0.7, 8, 0.7, 0.8, 0.8, 0.9)
    supported = assess_palm(observation, ParameterSet(base))
    tightened = deepcopy(base)
    tightened["PALM.RADIALITY_MIN"] = 0.75
    rejected = assess_palm(observation, ParameterSet(tightened))
    assert supported.state in {"PALM_TREE", "PALM_LIKE_CROWN"}
    assert rejected.state == "UNKNOWN_TREE"


def test_water_candidate_threshold_is_sensitivity_visible() -> None:
    base = {
        "WATER.TEXTURE_MAX": 0.45,
        "WATER.SPECULAR_SUPPORT_MIN": 0.4,
        "WATER.BANK_EDGE_MIN": 0.55,
        "WATER.CHANNEL_CONTINUITY_MIN": 0.6,
        "WATER.RIPARIAN_SUPPORT_MIN": 0.4,
        "WATER.MEANDER_SUPPORT_MIN": 0.3,
        "WATER.SHADOW_CONFLICT_MAX": 0.5,
        "WATER.CANDIDATE_MIN": 0.5,
        "WATER.SUPPORTED_MIN": 0.8,
        "HYDRO.CHANNEL_ELONGATION_MIN": 0.7,
        "HYDRO.BANK_PARALLELISM_MIN": 0.55,
        "HYDRO.CLOSED_SHORELINE_MIN": 0.8,
        "HYDRO.CANAL_LINEARITY_MIN": 0.85,
    }
    observation = WaterObservation(0.2, 0.6, 0.9, 0.7, 0.1, 0.1, 0.0, 0.8, 0.8, 0.0, 0.0)
    candidate = assess_water(observation, ParameterSet(base))
    tightened = deepcopy(base)
    tightened["WATER.CANDIDATE_MIN"] = 0.8
    unresolved = assess_water(observation, ParameterSet(tightened))
    assert candidate.state == "WATER_CANDIDATE"
    assert unresolved.state == "UNRESOLVED"


def test_quarry_negative_control_can_demote_supported_candidate() -> None:
    parameters = ParameterSet(
        {
            "QUARRY.EXPOSED_GROUND_MIN": 0.55,
            "QUARRY.BENCH_COUNT_MIN": 2.0,
            "QUARRY.BENCH_PARALLELISM_MIN": 0.55,
            "QUARRY.PIT_CONCAVITY_MIN": 0.45,
            "QUARRY.HIGHWALL_SUPPORT_MIN": 0.5,
            "QUARRY.HAUL_ROAD_SUPPORT_MIN": 0.45,
            "QUARRY.STOCKPILE_SUPPORT_MIN": 0.4,
            "QUARRY.PROCESSING_CONTEXT_MIN": 0.4,
            "QUARRY.SEDIMENT_CONTROL_MIN": 0.3,
            "QUARRY.CANDIDATE_MIN": 0.55,
            "QUARRY.SUPPORTED_MIN": 0.7,
            "QUARRY.NATURAL_SCARP_NEGATIVE_WEIGHT": 0.8,
            "QUARRY.LANDSLIDE_NEGATIVE_WEIGHT": 0.6,
            "QUARRY.ROAD_CUT_NEGATIVE_WEIGHT": 0.5,
            "QUARRY.KARST_NEGATIVE_WEIGHT": 0.5,
            "QUARRY.CONSTRUCTION_NEGATIVE_WEIGHT": 0.5,
        }
    )
    supported = assess_quarry(
        QuarryObservation(0.9, 5, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9),
        parameters,
    )
    demoted = assess_quarry(
        QuarryObservation(
            0.9,
            5,
            0.9,
            0.9,
            0.9,
            0.9,
            0.9,
            0.9,
            0.9,
            natural_scarp=1.0,
        ),
        parameters,
    )
    assert supported.state == "QUARRY_SUPPORTED"
    assert demoted.state == "QUARRY_CANDIDATE"


def _locator_params() -> dict[str, float]:
    return {
        "LOCATOR.TEXT_WEIGHT": 0.2,
        "LOCATOR.ROAD_GRAPH_WEIGHT": 0.2,
        "LOCATOR.HYDROGRAPHY_WEIGHT": 0.2,
        "LOCATOR.TERRAIN_WEIGHT": 0.1,
        "LOCATOR.BUILDING_WEIGHT": 0.1,
        "LOCATOR.LANDMARK_WEIGHT": 0.1,
        "LOCATOR.VEGETATION_WEIGHT": 0.02,
        "LOCATOR.MULTIFRAME_WEIGHT": 0.05,
        "LOCATOR.GENERIC_SIMILARITY_WEIGHT": 0.03,
        "LOCATOR.HARD_CONTRADICTION_PENALTY": 1.0,
        "LOCATOR.SOFT_CONTRADICTION_PENALTY": 0.05,
        "LOCATOR.MIN_CANDIDATES_PRESERVED": 2.0,
        "LOCATOR.MAX_CANDIDATES_PRESERVED": 5.0,
        "LOCATOR.RUNNER_UP_MARGIN_MIN": 0.08,
        "LOCATOR.L1_THRESHOLD": 0.2,
        "LOCATOR.L2_THRESHOLD": 0.35,
        "LOCATOR.L3_THRESHOLD": 0.5,
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


def _candidate(candidate_id: str, score: float) -> LocationCandidate:
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


def test_locator_runner_up_margin_changes_tie_state() -> None:
    base = _locator_params()
    candidates = [_candidate("A", 0.9), _candidate("B", 0.84)]
    tied = locate_scene(candidates, ParameterSet(base))
    relaxed = deepcopy(base)
    relaxed["LOCATOR.RUNNER_UP_MARGIN_MIN"] = 0.05
    unique = locate_scene(candidates, ParameterSet(relaxed))
    assert tied.state == "MULTIPLE_CANDIDATES"
    assert unique.state != "MULTIPLE_CANDIDATES"


def test_exact_rmse_boundary_controls_certification() -> None:
    params = ParameterSet(_locator_params())
    candidate = _candidate("A", 0.95)
    passing = locate_scene(
        [candidate],
        params,
        RegistrationMetrics(5, 2.0, 5.0, 15.0, 3.0),
    )
    failing = locate_scene(
        [candidate],
        params,
        RegistrationMetrics(5, 2.0001, 5.0, 15.0, 3.0),
    )
    assert passing.state == "EXACT_CERTIFIED"
    assert failing.state == "EXACT_PROVISIONAL"
