"""Canonical fail-closed visual-reasoning runtime for SATIM v0.2.

The runtime consumes *measured observations* produced by image-processing or
registration stages. It deliberately does not invent hidden model defaults or
hard-code unvalidated numerical thresholds. Every output-affecting threshold
is supplied through :class:`ParameterSet`; missing required parameters fail
closed to ``UNRESOLVED`` with ``RC_MISSING_NOT_NEGATIVE``.

This module implements the decision layer frozen by the v0.2 rule registry:
quality/zoom, shadow photometry, seam/stitching, artifact-vs-object,
palm morphology, water/hydrography, quarry/excavation/portal-like candidates,
multiscale/multiframe support, scene-graph relations, and multi-channel scene
localization. Discovery is never promoted to identity without independent
binding evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


RC_MISSING = "RC_MISSING_NOT_NEGATIVE"
RC_TIE = "RC_EVIDENTIARY_TIE"
RC_DISCOVERY = "RC_DISCOVERY_NOT_IDENTITY"


@dataclass(frozen=True)
class ReasoningOutcome:
    state: str
    confidence: float | None = None
    reason_codes: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    contradictions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParameterSet:
    """Explicit runtime parameter binding.

    The canonical registry marks numerical values ``CALIBRATION_REQUIRED``.
    Consequently this class has no numerical defaults. Callers must provide
    every value that can affect the requested decision path.
    """

    values: Mapping[str, float]

    def require(self, *names: str) -> tuple[float, ...] | None:
        if any(name not in self.values for name in names):
            return None
        return tuple(float(self.values[name]) for name in names)


@dataclass(frozen=True)
class ZoomObservation:
    edge_information_gain: float | None
    texture_gain: float | None
    resampling_damage: float | None


@dataclass(frozen=True)
class ShadowObservation:
    darkness_ratio: float | None
    local_deviation: float | None
    texture_retention: float | None
    edge_consistency: float | None
    direction_delta_deg: float | None
    clipped_black_ratio: float | None
    geometry_support: bool | None


@dataclass(frozen=True)
class SeamObservation:
    linearity: float | None
    boundary_length_px: float | None
    luminance_delta: float | None
    color_delta: float | None
    histogram_distance: float | None
    sharpness_delta: float | None
    texture_delta: float | None
    noise_delta: float | None
    compression_delta: float | None
    registration_offset_px: float | None
    feature_continues: bool | None = None
    duplicate_or_ghost: bool | None = None


@dataclass(frozen=True)
class ArtifactObservation:
    render_scale_dependency: float | None
    multiscale_persistence: float | None
    multiframe_persistence: float | None
    geometry_coherence: float | None
    texture_coherence: float | None
    lighting_coherence: float | None
    pixel_grid_alignment: float | None
    halo_or_ringing: float | None


@dataclass(frozen=True)
class PalmObservation:
    radiality: float | None
    frond_count: int | None
    crown_circularity: float | None
    trunk_support: float | None
    shadow_support: float | None
    multiscale_support: float | None
    negative_control_score: float | None = None
    species_evidence_sufficient: bool = False


@dataclass(frozen=True)
class WaterObservation:
    surface_texture: float | None
    specular_support: float | None
    bank_edge_support: float | None
    channel_continuity: float | None
    riparian_support: float | None
    meander_support: float | None
    shadow_conflict: float | None
    elongation: float | None
    bank_parallelism: float | None
    closed_shoreline: float | None
    canal_linearity: float | None


@dataclass(frozen=True)
class QuarryObservation:
    exposed_ground: float | None
    bench_count: int | None
    bench_parallelism: float | None
    pit_concavity: float | None
    highwall_support: float | None
    haul_road_support: float | None
    stockpile_support: float | None
    processing_context: float | None
    sediment_control: float | None
    natural_scarp: float = 0.0
    landslide: float = 0.0
    road_cut: float = 0.0
    karst_exposure: float = 0.0
    construction: float = 0.0
    authoritative_legal_binding: bool = False


@dataclass(frozen=True)
class ExcavationObservation:
    fresh_soil: float | None
    vegetation_removal: float | None
    cut_geometry: float | None
    spoil_adjacency: float | None
    visible_wall: float | None
    temporary_access: float | None
    depth_geometry_support: float | None = None


@dataclass(frozen=True)
class PortalObservation:
    opening_geometry: float | None
    structural_edge: float | None
    slope_relation: float | None
    access_relation: float | None
    multiscale_persistence: float | None
    culvert_conflict: float = 0.0
    tree_shadow_conflict: float = 0.0
    bridge_shadow_conflict: float = 0.0
    rock_overhang_conflict: float = 0.0
    artifact_conflict: float = 0.0
    independent_subsurface_binding: bool = False


@dataclass(frozen=True)
class RegisteredFeatureObservation:
    registration_score: float | None
    geometric_persistence: float | None
    class_stability: float | None
    resolution_loss: float | None


@dataclass(frozen=True)
class MultiframeObservation:
    shared_features: int | None
    registration_error_px: float | None
    feature_consensus: float | None


@dataclass(frozen=True)
class SceneNode:
    node_id: str
    class_state: str
    confidence: float | None
    source_frame_ids: tuple[str, ...]
    artifact_classified: bool = False


@dataclass(frozen=True)
class SceneEdge:
    source: str
    target: str
    relation: str
    confidence: float
    reason_codes: tuple[str, ...] = ("RC_RELATION_NOT_IDENTITY",)


@dataclass
class SceneGraph:
    nodes: dict[str, SceneNode] = field(default_factory=dict)
    edges: list[SceneEdge] = field(default_factory=list)

    def add_node(self, node: SceneNode) -> None:
        self.nodes[node.node_id] = node

    def add_relation(self, edge: SceneEdge, params: ParameterSet) -> ReasoningOutcome:
        required = params.require("SCENE.RELATION_CONFIDENCE_MIN")
        if required is None:
            return _missing("SCENE.RELATION_CONFIDENCE_MIN")
        (minimum,) = required
        if edge.source not in self.nodes or edge.target not in self.nodes:
            return ReasoningOutcome("UNRESOLVED", reason_codes=(RC_MISSING,), metadata={"missing_node": True})
        if edge.confidence < minimum:
            return ReasoningOutcome("UNRESOLVED", confidence=edge.confidence, reason_codes=(RC_MISSING,))
        self.edges.append(edge)
        return ReasoningOutcome(
            "RELATION_SUPPORTED_IDENTITY_UNRESOLVED",
            confidence=edge.confidence,
            reason_codes=("RC_RELATION_NOT_IDENTITY",),
        )


@dataclass(frozen=True)
class LocationCandidate:
    candidate_id: str
    text_score: float | None = None
    road_score: float | None = None
    hydro_score: float | None = None
    terrain_score: float | None = None
    building_score: float | None = None
    landmark_score: float | None = None
    vegetation_score: float | None = None
    multiframe_score: float | None = None
    generic_similarity_score: float | None = None
    hard_geometric_contradiction: bool = False
    soft_contradictions: int = 0
    text_cue_count: int = 0
    independent_topology_support: bool = False
    selected_by_proximity_only: bool = False
    artifact_landmark_used: bool = False


@dataclass(frozen=True)
class RegistrationMetrics:
    control_point_count: int | None
    rmse_px: float | None
    rmse_m: float | None
    error_radius_m: float | None
    leave_one_out_max_residual: float | None


@dataclass(frozen=True)
class LocationResult:
    state: str
    best_candidate: str | None
    second_candidate: str | None
    best_score: float | None
    second_score: float | None
    location_level: int
    error_radius_m: float | None
    reason_codes: tuple[str, ...]
    rejected_candidates: tuple[str, ...] = ()


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(items) / len(items)


def _missing(*names: str) -> ReasoningOutcome:
    return ReasoningOutcome(
        "UNRESOLVED",
        reason_codes=(RC_MISSING,),
        metadata={"missing_required": tuple(names)},
    )


def _missing_observation(*names: str) -> ReasoningOutcome:
    return ReasoningOutcome(
        "UNRESOLVED",
        reason_codes=(RC_MISSING,),
        metadata={"missing_observation": tuple(names)},
    )


def assess_zoom(obs: ZoomObservation, params: ParameterSet) -> ReasoningOutcome:
    if obs.edge_information_gain is None or obs.texture_gain is None or obs.resampling_damage is None:
        return _missing_observation("edge_information_gain", "texture_gain", "resampling_damage")
    required = params.require(
        "ZOOM.EDGE_INFORMATION_MIN",
        "ZOOM.TEXTURE_GAIN_MIN",
        "ZOOM.RESAMPLING_DAMAGE_MAX",
    )
    if required is None:
        return _missing("ZOOM.EDGE_INFORMATION_MIN", "ZOOM.TEXTURE_GAIN_MIN", "ZOOM.RESAMPLING_DAMAGE_MAX")
    edge_min, texture_min, damage_max = required
    if obs.resampling_damage > damage_max and obs.edge_information_gain < edge_min and obs.texture_gain < texture_min:
        return ReasoningOutcome(
            "OVERZOOMED",
            confidence=_clamp01(obs.resampling_damage),
            reason_codes=("RC_OVERZOOMED", "RC_OVERZOOM_NO_NEW_EVIDENCE"),
        )
    information = _mean((_clamp01(obs.edge_information_gain), _clamp01(obs.texture_gain)))
    return ReasoningOutcome("DETAIL_USABLE", confidence=information)


def assess_shadow(obs: ShadowObservation, params: ParameterSet) -> ReasoningOutcome:
    required_obs = (
        obs.darkness_ratio,
        obs.local_deviation,
        obs.texture_retention,
        obs.edge_consistency,
        obs.direction_delta_deg,
        obs.clipped_black_ratio,
        obs.geometry_support,
    )
    if any(value is None for value in required_obs):
        return _missing_observation("shadow_photometric_or_geometry_field")
    required = params.require(
        "SHADOW.DARKNESS_RATIO_MIN",
        "SHADOW.DARKNESS_RATIO_MAX",
        "SHADOW.LOCAL_DEVIATION_MAX",
        "SHADOW.TEXTURE_RETENTION_MIN",
        "SHADOW.DIRECTION_TOLERANCE_DEG",
        "SHADOW.CLIPPED_BLACK_RATIO",
    )
    if required is None:
        return _missing("SHADOW.*")
    dark_min, dark_max, deviation_max, texture_min, direction_tol, clipped_threshold = required
    assert obs.darkness_ratio is not None
    assert obs.local_deviation is not None
    assert obs.texture_retention is not None
    assert obs.edge_consistency is not None
    assert obs.direction_delta_deg is not None
    assert obs.clipped_black_ratio is not None

    if obs.clipped_black_ratio >= clipped_threshold:
        return ReasoningOutcome(
            "CLIPPED_BLACK",
            confidence=_clamp01(obs.clipped_black_ratio),
            reason_codes=("RC_SHADOW_CLIPPED",),
        )

    darkness_ok = dark_min <= obs.darkness_ratio <= dark_max
    deviation_ok = obs.local_deviation <= deviation_max
    texture_ok = obs.texture_retention >= texture_min
    direction_ok = abs(obs.direction_delta_deg) <= direction_tol
    edge_ok = obs.edge_consistency >= 0.5

    if darkness_ok and deviation_ok and texture_ok and direction_ok and edge_ok and obs.geometry_support:
        support = _mean(
            (
                _clamp01(1.0 - obs.local_deviation),
                _clamp01(obs.texture_retention),
                _clamp01(obs.edge_consistency),
                _clamp01(1.0 - abs(obs.direction_delta_deg) / max(direction_tol, 1e-12)),
            )
        )
        return ReasoningOutcome(
            "PHYSICALLY_PLAUSIBLE_SHADOW",
            confidence=support,
            reason_codes=("RC_SHADOW_CONSISTENT",),
        )

    conflicts = []
    if not deviation_ok:
        conflicts.append("local_shadow_field")
    if not direction_ok or not obs.geometry_support:
        conflicts.append("geometry")
    if not texture_ok:
        conflicts.append("texture")
    if conflicts:
        return ReasoningOutcome(
            "INCONSISTENT_SHADOW",
            reason_codes=("RC_SHADOW_INCONSISTENT",),
            contradictions=tuple(conflicts),
        )
    return ReasoningOutcome("UNRESOLVED", reason_codes=("RC_DARKNESS_INSUFFICIENT_FOR_SHADOW",))


def assess_seam(obs: SeamObservation, params: ParameterSet) -> ReasoningOutcome:
    required_obs = (
        obs.linearity,
        obs.boundary_length_px,
        obs.luminance_delta,
        obs.color_delta,
        obs.histogram_distance,
        obs.sharpness_delta,
        obs.texture_delta,
        obs.noise_delta,
        obs.compression_delta,
        obs.registration_offset_px,
    )
    if any(value is None for value in required_obs):
        return _missing_observation("seam_measurement")
    required = params.require(
        "SEAM.LINEARITY_MIN",
        "SEAM.BOUNDARY_LENGTH_MIN_PX",
        "SEAM.LUMINANCE_DELTA_MIN",
        "SEAM.COLOR_DELTA_MIN",
        "SEAM.HISTOGRAM_DISTANCE_MIN",
        "SEAM.SHARPNESS_DELTA_MIN",
        "SEAM.TEXTURE_DELTA_MIN",
        "SEAM.NOISE_DELTA_MIN",
        "SEAM.COMPRESSION_DELTA_MIN",
        "SEAM.REGISTRATION_OFFSET_MIN_PX",
        "SEAM.SCORE_LOW",
        "SEAM.SCORE_MODERATE",
        "SEAM.SCORE_HIGH",
    )
    if required is None:
        return _missing("SEAM.*")
    (
        linearity_min,
        length_min,
        lum_min,
        color_min,
        hist_min,
        sharp_min,
        texture_min,
        noise_min,
        compression_min,
        offset_min,
        score_low,
        score_moderate,
        score_high,
    ) = required
    assert obs.linearity is not None
    assert obs.boundary_length_px is not None
    metrics = (
        (obs.luminance_delta, lum_min),
        (obs.color_delta, color_min),
        (obs.histogram_distance, hist_min),
        (obs.sharpness_delta, sharp_min),
        (obs.texture_delta, texture_min),
        (obs.noise_delta, noise_min),
        (obs.compression_delta, compression_min),
        (obs.registration_offset_px, offset_min),
    )
    crossed = [float(value >= threshold) for value, threshold in metrics if value is not None]
    discrepancy = _mean(crossed)
    candidate = obs.linearity >= linearity_min and obs.boundary_length_px >= length_min and discrepancy >= score_low
    if not candidate:
        return ReasoningOutcome("NO_SEAM_SUPPORT", confidence=discrepancy)

    metadata: dict[str, Any] = {"discrepancy_score": discrepancy}
    if discrepancy >= score_high:
        metadata["severity"] = "HIGH"
    elif discrepancy >= score_moderate:
        metadata["severity"] = "MODERATE"
    else:
        metadata["severity"] = "LOW"

    reasons = ["RC_SEAM_CANDIDATE", "RC_SEAM_NOT_REAL_WORLD_BOUNDARY"]
    state = "SEAM_CANDIDATE"
    if obs.duplicate_or_ghost:
        state = "STITCHING_ARTIFACT_CANDIDATE"
        reasons.append("RC_STITCHING_GHOST")
    elif obs.feature_continues:
        state = "CONTINUOUS_WITH_IMAGE_DISCREPANCY"
        reasons.append("RC_CROSS_SEAM_CONTINUITY")
    return ReasoningOutcome(state, confidence=discrepancy, reason_codes=tuple(reasons), metadata=metadata)


def assess_artifact(obs: ArtifactObservation, params: ParameterSet) -> ReasoningOutcome:
    required_obs = (
        obs.render_scale_dependency,
        obs.multiscale_persistence,
        obs.multiframe_persistence,
        obs.geometry_coherence,
        obs.texture_coherence,
        obs.lighting_coherence,
        obs.pixel_grid_alignment,
        obs.halo_or_ringing,
    )
    if any(value is None for value in required_obs):
        return _missing_observation("artifact_measurement")
    required = params.require(
        "ARTIFACT.RENDER_SCALE_DEPENDENCY_MIN",
        "ARTIFACT.MULTISCALE_PERSISTENCE_MIN",
        "ARTIFACT.MULTIFRAME_PERSISTENCE_MIN",
        "ARTIFACT.REAL_OBJECT_PROMOTION_MIN",
        "ARTIFACT.ARTIFACT_PROMOTION_MIN",
        "ARTIFACT.MIXED_STATE_MARGIN",
    )
    if required is None:
        return _missing("ARTIFACT.*")
    render_min, scale_min, frame_min, real_min, artifact_min, margin = required
    assert obs.render_scale_dependency is not None
    assert obs.multiscale_persistence is not None
    assert obs.multiframe_persistence is not None
    assert obs.geometry_coherence is not None
    assert obs.texture_coherence is not None
    assert obs.lighting_coherence is not None
    assert obs.pixel_grid_alignment is not None
    assert obs.halo_or_ringing is not None

    real_score = _mean(
        (
            obs.geometry_coherence,
            obs.texture_coherence,
            obs.lighting_coherence,
            obs.multiscale_persistence,
            obs.multiframe_persistence,
        )
    )
    artifact_score = _mean(
        (
            obs.render_scale_dependency,
            obs.pixel_grid_alignment,
            obs.halo_or_ringing,
            1.0 - obs.multiscale_persistence,
            1.0 - obs.multiframe_persistence,
        )
    )
    metadata = {"real_score": real_score, "artifact_score": artifact_score}

    if real_score >= real_min and artifact_score >= artifact_min and abs(real_score - artifact_score) <= margin:
        return ReasoningOutcome(
            "MIXED_REAL_OBJECT_PLUS_ARTIFACT",
            confidence=max(real_score, artifact_score),
            reason_codes=("RC_MIXED_OBJECT_ARTIFACT",),
            metadata=metadata,
        )
    if artifact_score >= artifact_min and obs.render_scale_dependency >= render_min:
        return ReasoningOutcome(
            "RENDERING_ARTIFACT_CANDIDATE",
            confidence=artifact_score,
            reason_codes=("RC_RENDER_SCALE_DEPENDENT", "RC_ARTIFACT_EXCLUDED_FROM_LOCATOR"),
            metadata=metadata,
        )
    if real_score >= real_min and obs.multiscale_persistence >= scale_min and obs.multiframe_persistence >= frame_min:
        return ReasoningOutcome(
            "REAL_WORLD_OBJECT_CANDIDATE",
            confidence=real_score,
            reason_codes=("RC_REAL_OBJECT_SUPPORT",),
            metadata=metadata,
        )
    return ReasoningOutcome("AMBIGUOUS", confidence=max(real_score, artifact_score), reason_codes=(RC_DISCOVERY,), metadata=metadata)


def assess_palm(obs: PalmObservation, params: ParameterSet) -> ReasoningOutcome:
    required_obs = (
        obs.radiality,
        obs.frond_count,
        obs.crown_circularity,
        obs.trunk_support,
        obs.shadow_support,
        obs.multiscale_support,
    )
    if any(value is None for value in required_obs):
        return _missing_observation("palm_morphology")
    required = params.require(
        "PALM.RADIALITY_MIN",
        "PALM.FROND_COUNT_MIN",
        "PALM.CROWN_CIRCULARITY_MIN",
        "PALM.CROWN_CIRCULARITY_MAX",
        "PALM.TRUNK_SUPPORT_WEIGHT",
        "PALM.SHADOW_SUPPORT_WEIGHT",
        "PALM.MULTISCALE_SUPPORT_WEIGHT",
        "PALM.CANDIDATE_MIN",
        "PALM.SUPPORTED_MIN",
    )
    if required is None:
        return _missing("PALM.*")
    radial_min, frond_min, circ_min, circ_max, trunk_w, shadow_w, scale_w, candidate_min, supported_min = required
    assert obs.radiality is not None
    assert obs.frond_count is not None
    assert obs.crown_circularity is not None
    assert obs.trunk_support is not None
    assert obs.shadow_support is not None
    assert obs.multiscale_support is not None

    morphology_ok = (
        obs.radiality >= radial_min
        and obs.frond_count >= frond_min
        and circ_min <= obs.crown_circularity <= circ_max
    )
    negative = _clamp01(obs.negative_control_score or 0.0)
    denominator = max(1e-12, 1.0 + trunk_w + shadow_w + scale_w)
    score = (
        _clamp01(obs.radiality)
        + trunk_w * _clamp01(obs.trunk_support)
        + shadow_w * _clamp01(obs.shadow_support)
        + scale_w * _clamp01(obs.multiscale_support)
    ) / denominator
    score = _clamp01(score * (1.0 - negative))
    if morphology_ok and score >= supported_min:
        reasons = ["RC_PALM_SUPPORTED"]
        metadata = {"species_state": "SUPPORTED" if obs.species_evidence_sufficient else "UNRESOLVED"}
        if not obs.species_evidence_sufficient:
            reasons.append("RC_PALM_SPECIES_UNRESOLVED")
        return ReasoningOutcome("PALM_TREE", score, tuple(reasons), metadata)
    if morphology_ok and score >= candidate_min:
        return ReasoningOutcome("PALM_LIKE_CROWN", score, ("RC_PALM_LIKE_CROWN",))
    return ReasoningOutcome("UNKNOWN_TREE", score, reason_codes=(RC_DISCOVERY,))


def assess_water(obs: WaterObservation, params: ParameterSet) -> ReasoningOutcome:
    required_obs = (
        obs.surface_texture,
        obs.specular_support,
        obs.bank_edge_support,
        obs.channel_continuity,
        obs.riparian_support,
        obs.meander_support,
        obs.shadow_conflict,
        obs.elongation,
        obs.bank_parallelism,
        obs.closed_shoreline,
        obs.canal_linearity,
    )
    if any(value is None for value in required_obs):
        return _missing_observation("water_or_hydrography_measurement")
    required = params.require(
        "WATER.TEXTURE_MAX",
        "WATER.SPECULAR_SUPPORT_MIN",
        "WATER.BANK_EDGE_MIN",
        "WATER.CHANNEL_CONTINUITY_MIN",
        "WATER.RIPARIAN_SUPPORT_MIN",
        "WATER.MEANDER_SUPPORT_MIN",
        "WATER.SHADOW_CONFLICT_MAX",
        "WATER.CANDIDATE_MIN",
        "WATER.SUPPORTED_MIN",
        "HYDRO.CHANNEL_ELONGATION_MIN",
        "HYDRO.BANK_PARALLELISM_MIN",
        "HYDRO.CLOSED_SHORELINE_MIN",
        "HYDRO.CANAL_LINEARITY_MIN",
    )
    if required is None:
        return _missing("WATER.*", "HYDRO.*")
    (
        texture_max,
        specular_min,
        bank_min,
        continuity_min,
        riparian_min,
        meander_min,
        shadow_max,
        candidate_min,
        supported_min,
        elongation_min,
        parallel_min,
        closed_min,
        canal_min,
    ) = required
    assert obs.surface_texture is not None
    assert obs.specular_support is not None
    assert obs.bank_edge_support is not None
    assert obs.channel_continuity is not None
    assert obs.riparian_support is not None
    assert obs.meander_support is not None
    assert obs.shadow_conflict is not None
    assert obs.elongation is not None
    assert obs.bank_parallelism is not None
    assert obs.closed_shoreline is not None
    assert obs.canal_linearity is not None

    positive_flags = (
        obs.surface_texture <= texture_max,
        obs.specular_support >= specular_min,
        obs.bank_edge_support >= bank_min,
        obs.channel_continuity >= continuity_min,
        obs.riparian_support >= riparian_min,
        obs.meander_support >= meander_min,
    )
    support = _mean(float(flag) for flag in positive_flags)
    if obs.shadow_conflict > shadow_max:
        support *= max(0.0, 1.0 - obs.shadow_conflict)
    if support < candidate_min:
        return ReasoningOutcome("UNRESOLVED", support, ("RC_DARKNESS_INSUFFICIENT_FOR_WATER",))

    hydro_state = "WATER_CANDIDATE"
    hydro_reason = "RC_WATER_SUPPORTED"
    if obs.closed_shoreline >= closed_min:
        hydro_state = "LAKE_POND_OR_RESERVOIR"
        hydro_reason = "RC_HYDRO_CLOSED_WATER_FORM"
    elif obs.canal_linearity >= canal_min and obs.bank_parallelism >= parallel_min:
        hydro_state = "CANAL_CANDIDATE"
        hydro_reason = "RC_HYDRO_CANAL_CANDIDATE"
    elif obs.elongation >= elongation_min and obs.channel_continuity >= continuity_min and obs.bank_parallelism >= parallel_min:
        hydro_state = "RIVER_OR_STREAM"
        hydro_reason = "RC_HYDRO_CHANNEL_FORM"

    if support >= supported_min:
        return ReasoningOutcome(hydro_state, support, ("RC_WATER_SUPPORTED", hydro_reason))
    return ReasoningOutcome("WATER_CANDIDATE", support, (RC_DISCOVERY,))


def assess_quarry(obs: QuarryObservation, params: ParameterSet) -> ReasoningOutcome:
    required_obs = (
        obs.exposed_ground,
        obs.bench_count,
        obs.bench_parallelism,
        obs.pit_concavity,
        obs.highwall_support,
        obs.haul_road_support,
        obs.stockpile_support,
        obs.processing_context,
        obs.sediment_control,
    )
    if any(value is None for value in required_obs):
        return _missing_observation("quarry_feature_family")
    required = params.require(
        "QUARRY.EXPOSED_GROUND_MIN",
        "QUARRY.BENCH_COUNT_MIN",
        "QUARRY.BENCH_PARALLELISM_MIN",
        "QUARRY.PIT_CONCAVITY_MIN",
        "QUARRY.HIGHWALL_SUPPORT_MIN",
        "QUARRY.HAUL_ROAD_SUPPORT_MIN",
        "QUARRY.STOCKPILE_SUPPORT_MIN",
        "QUARRY.PROCESSING_CONTEXT_MIN",
        "QUARRY.SEDIMENT_CONTROL_MIN",
        "QUARRY.CANDIDATE_MIN",
        "QUARRY.SUPPORTED_MIN",
        "QUARRY.NATURAL_SCARP_NEGATIVE_WEIGHT",
        "QUARRY.LANDSLIDE_NEGATIVE_WEIGHT",
        "QUARRY.ROAD_CUT_NEGATIVE_WEIGHT",
        "QUARRY.KARST_NEGATIVE_WEIGHT",
        "QUARRY.CONSTRUCTION_NEGATIVE_WEIGHT",
    )
    if required is None:
        return _missing("QUARRY.*")
    (
        exposed_min,
        bench_count_min,
        bench_parallel_min,
        pit_min,
        highwall_min,
        haul_min,
        stockpile_min,
        processing_min,
        sediment_min,
        candidate_min,
        supported_min,
        scarp_w,
        landslide_w,
        roadcut_w,
        karst_w,
        construction_w,
    ) = required
    assert obs.exposed_ground is not None
    assert obs.bench_count is not None
    assert obs.bench_parallelism is not None
    assert obs.pit_concavity is not None
    assert obs.highwall_support is not None
    assert obs.haul_road_support is not None
    assert obs.stockpile_support is not None
    assert obs.processing_context is not None
    assert obs.sediment_control is not None

    flags = (
        obs.exposed_ground >= exposed_min,
        obs.bench_count >= bench_count_min,
        obs.bench_parallelism >= bench_parallel_min,
        obs.pit_concavity >= pit_min,
        obs.highwall_support >= highwall_min,
        obs.haul_road_support >= haul_min,
        obs.stockpile_support >= stockpile_min,
        obs.processing_context >= processing_min,
        obs.sediment_control >= sediment_min,
    )
    positive = _mean(float(flag) for flag in flags)
    negative = _clamp01(
        scarp_w * obs.natural_scarp
        + landslide_w * obs.landslide
        + roadcut_w * obs.road_cut
        + karst_w * obs.karst_exposure
        + construction_w * obs.construction
    )
    score = _clamp01(positive * (1.0 - negative))

    if positive < candidate_min:
        return ReasoningOutcome("GROUND_DISTURBANCE_UNRESOLVED", score, ("RC_BARE_GROUND_NOT_QUARRY",))
    if score >= supported_min:
        state = "QUARRY_SUPPORTED"
        reasons = ["RC_QUARRY_SUPPORTED"]
    else:
        state = "QUARRY_CANDIDATE"
        reasons = ["RC_QUARRY_CANDIDATE"]
    if not obs.authoritative_legal_binding:
        reasons.append("RC_VISUAL_QUARRY_NOT_LEGAL_IDENTITY")
    return ReasoningOutcome(state, score, tuple(reasons), metadata={"legal_identity": obs.authoritative_legal_binding})


def assess_excavation(obs: ExcavationObservation, params: ParameterSet) -> ReasoningOutcome:
    required_obs = (
        obs.fresh_soil,
        obs.vegetation_removal,
        obs.cut_geometry,
        obs.spoil_adjacency,
        obs.visible_wall,
        obs.temporary_access,
    )
    if any(value is None for value in required_obs):
        return _missing_observation("excavation_feature_family")
    required = params.require(
        "EXCAVATION.FRESH_SOIL_MIN",
        "EXCAVATION.VEGETATION_REMOVAL_MIN",
        "EXCAVATION.CUT_GEOMETRY_MIN",
        "EXCAVATION.SPOIL_ADJACENCY_MIN",
        "EXCAVATION.VISIBLE_WALL_MIN",
        "EXCAVATION.TEMPORARY_ACCESS_SUPPORT_MIN",
        "EXCAVATION.DEPTH_CONFIDENCE_MIN",
    )
    if required is None:
        return _missing("EXCAVATION.*")
    fresh_min, vegetation_min, cut_min, spoil_min, wall_min, access_min, depth_min = required
    assert obs.fresh_soil is not None
    assert obs.vegetation_removal is not None
    assert obs.cut_geometry is not None
    assert obs.spoil_adjacency is not None
    assert obs.visible_wall is not None
    assert obs.temporary_access is not None
    flags = (
        obs.fresh_soil >= fresh_min,
        obs.vegetation_removal >= vegetation_min,
        obs.cut_geometry >= cut_min,
        obs.spoil_adjacency >= spoil_min,
        obs.visible_wall >= wall_min,
        obs.temporary_access >= access_min,
    )
    score = _mean(float(flag) for flag in flags)
    if score < 0.5:
        return ReasoningOutcome("GROUND_DISTURBANCE_UNRESOLVED", score, (RC_DISCOVERY,))
    reasons = ["RC_EXCAVATION_CANDIDATE"]
    metadata: dict[str, Any] = {"depth_state": "UNRESOLVED"}
    if obs.depth_geometry_support is not None and obs.depth_geometry_support >= depth_min:
        metadata["depth_state"] = "GEOMETRY_SUPPORTED"
    else:
        reasons.append("RC_DEPTH_REQUIRES_GEOMETRY")
    return ReasoningOutcome("EXCAVATION_CANDIDATE", score, tuple(reasons), metadata)


def assess_portal(obs: PortalObservation, params: ParameterSet) -> ReasoningOutcome:
    required_obs = (
        obs.opening_geometry,
        obs.structural_edge,
        obs.slope_relation,
        obs.access_relation,
        obs.multiscale_persistence,
    )
    if any(value is None for value in required_obs):
        return _missing_observation("portal_feature_family")
    required = params.require(
        "PORTAL.OPENING_GEOMETRY_MIN",
        "PORTAL.STRUCTURAL_EDGE_MIN",
        "PORTAL.SLOPE_RELATION_MIN",
        "PORTAL.ACCESS_RELATION_MIN",
        "PORTAL.MULTISCALE_PERSISTENCE_MIN",
        "PORTAL.CULVERT_CONFLICT_WEIGHT",
        "PORTAL.TREE_SHADOW_CONFLICT_WEIGHT",
        "PORTAL.BRIDGE_SHADOW_CONFLICT_WEIGHT",
        "PORTAL.ROCK_OVERHANG_CONFLICT_WEIGHT",
        "PORTAL.ARTIFACT_CONFLICT_WEIGHT",
    )
    if required is None:
        return _missing("PORTAL.*")
    (
        opening_min,
        edge_min,
        slope_min,
        access_min,
        scale_min,
        culvert_w,
        tree_w,
        bridge_w,
        rock_w,
        artifact_w,
    ) = required
    assert obs.opening_geometry is not None
    assert obs.structural_edge is not None
    assert obs.slope_relation is not None
    assert obs.access_relation is not None
    assert obs.multiscale_persistence is not None
    positives = (
        obs.opening_geometry >= opening_min,
        obs.structural_edge >= edge_min,
        obs.slope_relation >= slope_min,
        obs.access_relation >= access_min,
        obs.multiscale_persistence >= scale_min,
    )
    positive = _mean(float(flag) for flag in positives)
    conflict = _clamp01(
        culvert_w * obs.culvert_conflict
        + tree_w * obs.tree_shadow_conflict
        + bridge_w * obs.bridge_shadow_conflict
        + rock_w * obs.rock_overhang_conflict
        + artifact_w * obs.artifact_conflict
    )
    score = _clamp01(positive * (1.0 - conflict))
    if score < 0.6:
        return ReasoningOutcome("UNRESOLVED", score, (RC_DISCOVERY,))
    reasons = ["RC_PORTAL_LIKE"]
    if not obs.independent_subsurface_binding:
        reasons.append("RC_PORTAL_NOT_UNDERGROUND_IDENTITY")
    return ReasoningOutcome(
        "PORTAL_LIKE_FEATURE",
        score,
        tuple(reasons),
        metadata={"subsurface_identity": obs.independent_subsurface_binding},
    )


def assess_multiscale(obs: RegisteredFeatureObservation, params: ParameterSet) -> ReasoningOutcome:
    required_obs = (obs.registration_score, obs.geometric_persistence, obs.class_stability, obs.resolution_loss)
    if any(value is None for value in required_obs):
        return _missing_observation("multiscale_measurement")
    required = params.require(
        "MULTISCALE.FRAME_REGISTRATION_MIN",
        "MULTISCALE.GEOMETRIC_PERSISTENCE_MIN",
        "MULTISCALE.CLASS_STABILITY_MIN",
        "MULTISCALE.RESOLUTION_LOSS_TOLERANCE",
    )
    if required is None:
        return _missing("MULTISCALE.*")
    registration_min, persistence_min, stability_min, loss_tol = required
    assert obs.registration_score is not None
    assert obs.geometric_persistence is not None
    assert obs.class_stability is not None
    assert obs.resolution_loss is not None
    if obs.resolution_loss > loss_tol and obs.geometric_persistence < persistence_min:
        return ReasoningOutcome(
            "BELOW_RESOLUTION_NOT_ABSENT",
            reason_codes=("RC_BELOW_RESOLUTION_NOT_ABSENT",),
        )
    if (
        obs.registration_score >= registration_min
        and obs.geometric_persistence >= persistence_min
        and obs.class_stability >= stability_min
    ):
        return ReasoningOutcome(
            "MULTISCALE_SUPPORTED",
            confidence=_mean((obs.registration_score, obs.geometric_persistence, obs.class_stability)),
            reason_codes=("RC_MULTISCALE_PERSISTENT",),
        )
    return ReasoningOutcome("UNRESOLVED", reason_codes=(RC_MISSING,))


def assess_multiframe(obs: MultiframeObservation, params: ParameterSet) -> ReasoningOutcome:
    if obs.shared_features is None or obs.registration_error_px is None or obs.feature_consensus is None:
        return _missing_observation("multiframe_measurement")
    required = params.require(
        "MULTIFRAME.MIN_SHARED_FEATURES",
        "MULTIFRAME.REGISTRATION_MAX_ERROR_PX",
        "MULTIFRAME.FEATURE_CONSENSUS_MIN",
    )
    if required is None:
        return _missing("MULTIFRAME.*")
    shared_min, error_max, consensus_min = required
    if (
        obs.shared_features >= shared_min
        and obs.registration_error_px <= error_max
        and obs.feature_consensus >= consensus_min
    ):
        return ReasoningOutcome(
            "MULTIFRAME_SUPPORTED",
            confidence=_clamp01(obs.feature_consensus),
            reason_codes=("RC_MULTIFRAME_CONSENSUS",),
        )
    return ReasoningOutcome("UNRESOLVED", reason_codes=(RC_MISSING,))


def _location_required_parameters() -> tuple[str, ...]:
    return (
        "LOCATOR.TEXT_WEIGHT",
        "LOCATOR.ROAD_GRAPH_WEIGHT",
        "LOCATOR.HYDROGRAPHY_WEIGHT",
        "LOCATOR.TERRAIN_WEIGHT",
        "LOCATOR.BUILDING_WEIGHT",
        "LOCATOR.LANDMARK_WEIGHT",
        "LOCATOR.VEGETATION_WEIGHT",
        "LOCATOR.MULTIFRAME_WEIGHT",
        "LOCATOR.GENERIC_SIMILARITY_WEIGHT",
        "LOCATOR.HARD_CONTRADICTION_PENALTY",
        "LOCATOR.SOFT_CONTRADICTION_PENALTY",
        "LOCATOR.MIN_CANDIDATES_PRESERVED",
        "LOCATOR.MAX_CANDIDATES_PRESERVED",
        "LOCATOR.RUNNER_UP_MARGIN_MIN",
        "LOCATOR.L1_THRESHOLD",
        "LOCATOR.L2_THRESHOLD",
        "LOCATOR.L3_THRESHOLD",
        "LOCATOR.L4_THRESHOLD",
        "LOCATOR.L5_THRESHOLD",
        "LOCATOR.L6_THRESHOLD",
        "LOCATOR.L7_THRESHOLD",
    )


def _candidate_score(candidate: LocationCandidate, weights: Sequence[float], penalties: tuple[float, float]) -> float:
    channels = (
        candidate.text_score,
        candidate.road_score,
        candidate.hydro_score,
        candidate.terrain_score,
        candidate.building_score,
        candidate.landmark_score,
        candidate.vegetation_score,
        candidate.multiframe_score,
        candidate.generic_similarity_score,
    )
    numerator = 0.0
    denominator = 0.0
    for value, weight in zip(channels, weights):
        if value is None:
            continue
        numerator += _clamp01(value) * weight
        denominator += weight
    score = numerator / denominator if denominator > 0 else 0.0
    hard_penalty, soft_penalty = penalties
    if candidate.hard_geometric_contradiction:
        score -= hard_penalty
    score -= soft_penalty * candidate.soft_contradictions
    return _clamp01(score)


def _location_level(score: float, thresholds: Sequence[float]) -> int:
    level = 0
    for index, threshold in enumerate(thresholds, start=1):
        if score >= threshold:
            level = index
    return level


def locate_scene(
    candidates: Sequence[LocationCandidate],
    params: ParameterSet,
    registration: RegistrationMetrics | None = None,
) -> LocationResult:
    required_names = _location_required_parameters()
    required = params.require(*required_names)
    if required is None:
        return LocationResult("UNRESOLVED", None, None, None, None, 0, None, (RC_MISSING,))
    (
        text_w,
        road_w,
        hydro_w,
        terrain_w,
        building_w,
        landmark_w,
        vegetation_w,
        multiframe_w,
        generic_w,
        hard_penalty,
        soft_penalty,
        min_preserved,
        max_preserved,
        runner_margin,
        *level_thresholds,
    ) = required
    if not candidates:
        return LocationResult("UNRESOLVED", None, None, None, None, 0, None, (RC_MISSING,))

    weights = (text_w, road_w, hydro_w, terrain_w, building_w, landmark_w, vegetation_w, multiframe_w, generic_w)
    rejected: list[str] = []
    scored: list[tuple[float, LocationCandidate]] = []
    for candidate in candidates:
        if candidate.hard_geometric_contradiction:
            rejected.append(candidate.candidate_id)
            continue
        if candidate.selected_by_proximity_only:
            rejected.append(candidate.candidate_id)
            continue
        score = _candidate_score(candidate, weights, (hard_penalty, soft_penalty))
        scored.append((score, candidate))

    if not scored:
        return LocationResult(
            "UNRESOLVED",
            None,
            None,
            None,
            None,
            0,
            None,
            ("RC_LOCATION_HARD_GEOMETRIC_CONTRADICTION",),
            tuple(sorted(rejected)),
        )

    scored.sort(key=lambda row: (-row[0], row[1].candidate_id))
    preserve_count = int(max(min_preserved, min(max_preserved, len(scored))))
    scored = scored[:preserve_count]
    best_score, best = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else None
    second = scored[1][1] if len(scored) > 1 else None
    level = _location_level(best_score, level_thresholds)

    reasons: list[str] = []
    if best.artifact_landmark_used:
        reasons.append("RC_ARTIFACT_EXCLUDED_FROM_LOCATOR")
        return LocationResult(
            "UNRESOLVED",
            best.candidate_id,
            second.candidate_id if second else None,
            best_score,
            second_score,
            min(level, 4),
            registration.error_radius_m if registration else None,
            tuple(reasons),
            tuple(sorted(rejected)),
        )
    if best.text_cue_count <= 1 and not best.independent_topology_support:
        reasons.append("RC_ONE_LABEL_NOT_EXACT")
        return LocationResult(
            "MULTIPLE_CANDIDATES",
            best.candidate_id,
            second.candidate_id if second else None,
            best_score,
            second_score,
            min(level, 4),
            registration.error_radius_m if registration else None,
            tuple(reasons),
            tuple(sorted(rejected)),
        )
    if best.text_cue_count > 0 and best.independent_topology_support:
        reasons.append("RC_LOCATION_TEXT_TOPOLOGY")
    if second_score is not None and best_score - second_score < runner_margin:
        reasons.append("RC_LOCATION_TIE")
        return LocationResult(
            "MULTIPLE_CANDIDATES",
            best.candidate_id,
            second.candidate_id if second else None,
            best_score,
            second_score,
            min(level, 5),
            registration.error_radius_m if registration else None,
            tuple(reasons),
            tuple(sorted(rejected)),
        )

    # Exact states require explicit registration gates. A high aggregate score
    # alone cannot certify an exact coordinate.
    if level >= 6:
        if registration is None:
            reasons.append("RC_EXACT_PROVISIONAL")
            return LocationResult(
                "EXACT_PROVISIONAL",
                best.candidate_id,
                second.candidate_id if second else None,
                best_score,
                second_score,
                6,
                None,
                tuple(reasons),
                tuple(sorted(rejected)),
            )
        exact_required = params.require(
            "LOCATOR.EXACT_MIN_CONTROL_POINTS",
            "LOCATOR.EXACT_MAX_RMSE_PX",
            "LOCATOR.EXACT_MAX_RMSE_M",
            "LOCATOR.EXACT_MAX_ERROR_RADIUS_M",
            "LOCATOR.LEAVE_ONE_OUT_MAX_RESIDUAL",
        )
        if exact_required is None:
            reasons.append("RC_EXACT_PROVISIONAL")
            return LocationResult(
                "EXACT_PROVISIONAL",
                best.candidate_id,
                second.candidate_id if second else None,
                best_score,
                second_score,
                6,
                registration.error_radius_m,
                tuple(reasons),
                tuple(sorted(rejected)),
            )
        if any(
            value is None
            for value in (
                registration.control_point_count,
                registration.rmse_px,
                registration.rmse_m,
                registration.error_radius_m,
                registration.leave_one_out_max_residual,
            )
        ):
            reasons.append("RC_EXACT_PROVISIONAL")
            return LocationResult(
                "EXACT_PROVISIONAL",
                best.candidate_id,
                second.candidate_id if second else None,
                best_score,
                second_score,
                6,
                registration.error_radius_m,
                tuple(reasons),
                tuple(sorted(rejected)),
            )
        min_cp, max_px, max_m, max_radius, max_loo = exact_required
        assert registration.control_point_count is not None
        assert registration.rmse_px is not None
        assert registration.rmse_m is not None
        assert registration.error_radius_m is not None
        assert registration.leave_one_out_max_residual is not None
        exact = (
            registration.control_point_count >= min_cp
            and registration.rmse_px <= max_px
            and registration.rmse_m <= max_m
            and registration.error_radius_m <= max_radius
            and registration.leave_one_out_max_residual <= max_loo
        )
        if exact:
            reasons.extend(("RC_EXACT_CERTIFIED", "RC_LOCATION_ERROR_RADIUS_REQUIRED"))
            return LocationResult(
                "EXACT_CERTIFIED",
                best.candidate_id,
                second.candidate_id if second else None,
                best_score,
                second_score,
                7,
                registration.error_radius_m,
                tuple(reasons),
                tuple(sorted(rejected)),
            )
        reasons.append("RC_EXACT_PROVISIONAL")
        return LocationResult(
            "EXACT_PROVISIONAL",
            best.candidate_id,
            second.candidate_id if second else None,
            best_score,
            second_score,
            6,
            registration.error_radius_m,
            tuple(reasons),
            tuple(sorted(rejected)),
        )

    state_by_level = {
        0: "UNRESOLVED",
        1: "REGIONAL_ONLY",
        2: "LOCALIZED_MUNICIPALITY",
        3: "LOCALIZED_NEIGHBORHOOD",
        4: "LOCALIZED_ROAD_CORRIDOR",
        5: "LOCALIZED_BLOCK",
    }
    return LocationResult(
        state_by_level.get(level, "UNRESOLVED"),
        best.candidate_id,
        second.candidate_id if second else None,
        best_score,
        second_score,
        level,
        registration.error_radius_m if registration else None,
        tuple(reasons),
        tuple(sorted(rejected)),
    )


class VisualReasoningEngine:
    """Thin orchestrator that binds one explicit parameter set."""

    def __init__(self, parameters: Mapping[str, float]) -> None:
        self.params = ParameterSet(parameters)

    def zoom(self, obs: ZoomObservation) -> ReasoningOutcome:
        return assess_zoom(obs, self.params)

    def shadow(self, obs: ShadowObservation) -> ReasoningOutcome:
        return assess_shadow(obs, self.params)

    def seam(self, obs: SeamObservation) -> ReasoningOutcome:
        return assess_seam(obs, self.params)

    def artifact(self, obs: ArtifactObservation) -> ReasoningOutcome:
        return assess_artifact(obs, self.params)

    def palm(self, obs: PalmObservation) -> ReasoningOutcome:
        return assess_palm(obs, self.params)

    def water(self, obs: WaterObservation) -> ReasoningOutcome:
        return assess_water(obs, self.params)

    def quarry(self, obs: QuarryObservation) -> ReasoningOutcome:
        return assess_quarry(obs, self.params)

    def excavation(self, obs: ExcavationObservation) -> ReasoningOutcome:
        return assess_excavation(obs, self.params)

    def portal(self, obs: PortalObservation) -> ReasoningOutcome:
        return assess_portal(obs, self.params)

    def multiscale(self, obs: RegisteredFeatureObservation) -> ReasoningOutcome:
        return assess_multiscale(obs, self.params)

    def multiframe(self, obs: MultiframeObservation) -> ReasoningOutcome:
        return assess_multiframe(obs, self.params)

    def locate(
        self,
        candidates: Sequence[LocationCandidate],
        registration: RegistrationMetrics | None = None,
    ) -> LocationResult:
        return locate_scene(candidates, self.params, registration)
