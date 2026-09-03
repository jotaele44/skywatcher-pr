"""SATIM imagery-seam observation and causal-origin firewall.

Legacy ``TILE_SEAM_*`` labels are retained for backwards compatibility with
existing calibration ledgers. They describe *visual seam evidence only* and
MUST NOT be interpreted as proof of a renderer tile edge, source mosaic
cutline, shadow boundary, or physical ground feature.

Causal identity is represented separately by ``classify_seam_origin``. The
classifier preserves the complete candidate-origin set and resolves an origin
only when an origin-specific PASS gate is satisfied without a competing PASS.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Legacy observation labels (backwards compatible; not causal identities)
# ---------------------------------------------------------------------------
TILE_SEAM_PROBABLE = "TILE_SEAM_PROBABLE"
TILE_SEAM_CANDIDATE = "TILE_SEAM_CANDIDATE"
TILE_SEAM_INSUFFICIENT = "TILE_SEAM_INSUFFICIENT"

OBS_RADIOMETRIC = "RADIOMETRIC_DISCONTINUITY"
OBS_GEOMETRIC = "GEOMETRIC_REGISTRATION_DISCONTINUITY"
OBS_RADIOMETRIC_AND_GEOMETRIC = "RADIOMETRIC_AND_GEOMETRIC"
OBS_UNRESOLVED = "UNRESOLVED"

BEHAVIOR_GROUND_FIXED = "GROUND_FIXED"
BEHAVIOR_SCREEN_FIXED = "SCREEN_FIXED"
BEHAVIOR_TILE_GRID_BOUND = "TILE_GRID_BOUND"
BEHAVIOR_MIXED = "MIXED"
BEHAVIOR_UNRESOLVED = "UNRESOLVED"

ORIGIN_SOURCE_MOSAIC_CUTLINE = "SOURCE_MOSAIC_CUTLINE"
ORIGIN_DISPLAY_TILE_EDGE = "DISPLAY_TILE_EDGE"
ORIGIN_VIEWPORT_COMPOSITING_ARTIFACT = "VIEWPORT_COMPOSITING_ARTIFACT"
ORIGIN_NATURAL_SHADOW_BOUNDARY = "NATURAL_SHADOW_BOUNDARY"
ORIGIN_PHYSICAL_GROUND_FEATURE = "PHYSICAL_GROUND_FEATURE"
ORIGIN_COMPRESSION_OR_RESAMPLING = "COMPRESSION_OR_RESAMPLING_ARTIFACT"
ORIGIN_UNRESOLVED = "UNRESOLVED"

STATE_PASS = "PASS"
STATE_FAIL = "FAIL"
STATE_OPEN = "OPEN"
STATE_BLOCKED = "BLOCKED"
STATE_PROVISIONAL = "PROVISIONAL"
STATE_UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class TileSeamEvidence:
    """Derived evidence for imagery-seam calibration.

    The original boolean fields are retained unchanged. New tri-state fields
    are ``True`` / ``False`` / ``None`` so absence of evidence never silently
    becomes negative evidence.

    Raw coordinates, EXIF, or identifiable property imagery should not be
    stored in public calibration fixtures.
    """

    # Legacy visual evidence.
    crosses_landcover_classes: bool = False
    persists_across_zoomed_frames: bool = False
    roof_or_object_texture_split: bool = False
    object_anchors_consistent: bool = False
    follows_physical_geometry: bool = False
    shadow_explanation_plausible: bool = False
    raw_coordinate_released: bool = False

    # Explicit observation axis.
    radiometric_discontinuity: bool = False
    geometric_registration_discontinuity: bool = False

    # Coordinate-behavior / causal gates. None means not tested / unknown.
    ground_fixed_under_pan: bool | None = None
    screen_fixed_under_pan: bool | None = None
    provider_tile_grid_binding: bool | None = None
    persists_across_adjacent_zoom_levels: bool | None = None

    # Independent causal tests.
    independent_ground_feature_binding: bool | None = None
    shadow_morphology_support: bool | None = None
    source_mosaic_metadata_binding: bool | None = None
    alternate_basemap_same_boundary: bool | None = None
    compression_or_resampling_support: bool | None = None


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _optional_bool(value: object) -> bool | None:
    """Parse a tri-state boolean without promoting arbitrary strings to True."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        norm = value.strip().lower()
        if norm in {"", "none", "null", "unknown", "unresolved", "na", "n/a"}:
            return None
        if norm in {"1", "true", "yes", "y"}:
            return True
        if norm in {"0", "false", "no", "n"}:
            return False
    return None


def evidence_from_mapping(row: Mapping[str, object]) -> TileSeamEvidence:
    """Build ``TileSeamEvidence`` from a CSV/JSON-like row."""

    return TileSeamEvidence(
        crosses_landcover_classes=_truthy(row.get("crosses_landcover_classes", False)),
        persists_across_zoomed_frames=_truthy(row.get("persists_across_zoomed_frames", False)),
        roof_or_object_texture_split=_truthy(row.get("roof_or_object_texture_split", False)),
        object_anchors_consistent=_truthy(row.get("object_anchors_consistent", False)),
        follows_physical_geometry=_truthy(row.get("follows_physical_geometry", False)),
        shadow_explanation_plausible=_truthy(row.get("shadow_explanation_plausible", False)),
        raw_coordinate_released=_truthy(row.get("raw_coordinate_released", False)),
        radiometric_discontinuity=_truthy(row.get("radiometric_discontinuity", False)),
        geometric_registration_discontinuity=_truthy(
            row.get("geometric_registration_discontinuity", False)
        ),
        ground_fixed_under_pan=_optional_bool(row.get("ground_fixed_under_pan")),
        screen_fixed_under_pan=_optional_bool(row.get("screen_fixed_under_pan")),
        provider_tile_grid_binding=_optional_bool(row.get("provider_tile_grid_binding")),
        persists_across_adjacent_zoom_levels=_optional_bool(
            row.get("persists_across_adjacent_zoom_levels")
        ),
        independent_ground_feature_binding=_optional_bool(
            row.get("independent_ground_feature_binding")
        ),
        shadow_morphology_support=_optional_bool(row.get("shadow_morphology_support")),
        source_mosaic_metadata_binding=_optional_bool(
            row.get("source_mosaic_metadata_binding")
        ),
        alternate_basemap_same_boundary=_optional_bool(
            row.get("alternate_basemap_same_boundary")
        ),
        compression_or_resampling_support=_optional_bool(
            row.get("compression_or_resampling_support")
        ),
    )


def _observed_discontinuity(evidence: TileSeamEvidence) -> bool:
    return evidence.radiometric_discontinuity or evidence.geometric_registration_discontinuity


def _observation_axis(evidence: TileSeamEvidence) -> str:
    if evidence.radiometric_discontinuity and evidence.geometric_registration_discontinuity:
        return OBS_RADIOMETRIC_AND_GEOMETRIC
    if evidence.radiometric_discontinuity:
        return OBS_RADIOMETRIC
    if evidence.geometric_registration_discontinuity:
        return OBS_GEOMETRIC
    return OBS_UNRESOLVED


def _coordinate_behavior_axis(evidence: TileSeamEvidence) -> str:
    flags = {
        BEHAVIOR_GROUND_FIXED: evidence.ground_fixed_under_pan is True,
        BEHAVIOR_SCREEN_FIXED: evidence.screen_fixed_under_pan is True,
        BEHAVIOR_TILE_GRID_BOUND: evidence.provider_tile_grid_binding is True,
    }
    active = [name for name, on in flags.items() if on]
    if not active:
        return BEHAVIOR_UNRESOLVED
    if len(active) == 1:
        return active[0]
    return BEHAVIOR_MIXED


def _candidate(state: str, reasons: list[str], falsifiers: list[str] | None = None) -> dict[str, object]:
    return {
        "state": state,
        "reasons": reasons,
        "falsifiers": falsifiers or [],
    }


def classify_seam_origin(evidence: TileSeamEvidence) -> dict[str, object]:
    """Classify causal origin without collapsing the candidate set.

    Semantics:
    - one still image can PASS an observed discontinuity, but cannot by itself
      PASS SOURCE_MOSAIC_CUTLINE or DISPLAY_TILE_EDGE;
    - screen-fixed behavior is evidence for a viewport/UI compositing artifact,
      not proof of a provider tile edge;
    - renderer tile-edge identity requires provider tile-grid binding;
    - physical-ground identity requires independent binding, not persistence or
      visual similarity alone;
    - authoritative but conflicting bindings remain unresolved rather than being
      resolved by score or deterministic ordering.
    """

    observed = _observed_discontinuity(evidence)
    candidates: dict[str, dict[str, object]] = {}

    # SOURCE_MOSAIC_CUTLINE
    if not observed:
        candidates[ORIGIN_SOURCE_MOSAIC_CUTLINE] = _candidate(
            STATE_FAIL, ["no radiometric/geometric discontinuity observed"]
        )
    elif evidence.independent_ground_feature_binding is True:
        candidates[ORIGIN_SOURCE_MOSAIC_CUTLINE] = _candidate(
            STATE_FAIL,
            ["independent physical-ground binding conflicts with source-mosaic identity"],
        )
    elif evidence.source_mosaic_metadata_binding is True:
        candidates[ORIGIN_SOURCE_MOSAIC_CUTLINE] = _candidate(
            STATE_PASS,
            ["authoritative source-mosaic metadata binding", "discontinuity observed"],
            ["independent contradictory ground binding"],
        )
    else:
        required = {
            "ground_fixed_under_pan": evidence.ground_fixed_under_pan,
            "persists_across_adjacent_zoom_levels": evidence.persists_across_adjacent_zoom_levels,
            "provider_tile_grid_binding_is_false": (
                None
                if evidence.provider_tile_grid_binding is None
                else not evidence.provider_tile_grid_binding
            ),
            "independent_ground_feature_binding_is_false": (
                None
                if evidence.independent_ground_feature_binding is None
                else not evidence.independent_ground_feature_binding
            ),
        }
        if any(value is False for value in required.values()):
            candidates[ORIGIN_SOURCE_MOSAIC_CUTLINE] = _candidate(
                STATE_FAIL,
                [f"failed gate: {name}" for name, value in required.items() if value is False],
            )
        elif all(value is True for value in required.values()):
            candidates[ORIGIN_SOURCE_MOSAIC_CUTLINE] = _candidate(
                STATE_PROVISIONAL,
                [
                    "ground-fixed under pan",
                    "persists at adjacent zoom levels",
                    "not bound to provider tile grid",
                    "no independent physical-ground binding",
                ],
                ["provider tile-grid binding", "independent physical-ground binding"],
            )
        else:
            candidates[ORIGIN_SOURCE_MOSAIC_CUTLINE] = _candidate(
                STATE_BLOCKED,
                [f"untested gate: {name}" for name, value in required.items() if value is None],
            )

    # DISPLAY_TILE_EDGE: provider tile-grid identity, not screen-lock identity.
    if not observed:
        candidates[ORIGIN_DISPLAY_TILE_EDGE] = _candidate(
            STATE_FAIL, ["no radiometric/geometric discontinuity observed"]
        )
    elif evidence.screen_fixed_under_pan is True:
        candidates[ORIGIN_DISPLAY_TILE_EDGE] = _candidate(
            STATE_FAIL,
            ["screen-fixed behavior favors viewport/UI compositing, not a georeferenced tile edge"],
        )
    elif evidence.provider_tile_grid_binding is True:
        if evidence.independent_ground_feature_binding is True:
            candidates[ORIGIN_DISPLAY_TILE_EDGE] = _candidate(
                STATE_UNRESOLVED,
                ["provider tile-grid binding conflicts with independent physical-ground binding"],
            )
        else:
            candidates[ORIGIN_DISPLAY_TILE_EDGE] = _candidate(
                STATE_PASS,
                ["provider tile-grid binding", "discontinuity observed"],
                ["independent contradictory ground binding"],
            )
    elif evidence.provider_tile_grid_binding is False:
        candidates[ORIGIN_DISPLAY_TILE_EDGE] = _candidate(
            STATE_FAIL, ["candidate is not bound to the provider tile grid"]
        )
    else:
        candidates[ORIGIN_DISPLAY_TILE_EDGE] = _candidate(
            STATE_BLOCKED, ["provider tile-grid binding not tested"]
        )

    # VIEWPORT_COMPOSITING_ARTIFACT
    if evidence.screen_fixed_under_pan is True:
        if evidence.ground_fixed_under_pan is False:
            candidates[ORIGIN_VIEWPORT_COMPOSITING_ARTIFACT] = _candidate(
                STATE_PASS,
                ["screen-fixed under pan", "not ground-fixed under pan"],
            )
        else:
            candidates[ORIGIN_VIEWPORT_COMPOSITING_ARTIFACT] = _candidate(
                STATE_PROVISIONAL,
                ["screen-fixed under pan"],
            )
    elif evidence.screen_fixed_under_pan is False:
        candidates[ORIGIN_VIEWPORT_COMPOSITING_ARTIFACT] = _candidate(
            STATE_FAIL, ["candidate moves with scene rather than viewport"]
        )
    else:
        candidates[ORIGIN_VIEWPORT_COMPOSITING_ARTIFACT] = _candidate(
            STATE_BLOCKED, ["screen-lock behavior not tested"]
        )

    # NATURAL_SHADOW_BOUNDARY
    if evidence.shadow_morphology_support is True or evidence.shadow_explanation_plausible:
        candidates[ORIGIN_NATURAL_SHADOW_BOUNDARY] = _candidate(
            STATE_PROVISIONAL,
            ["shadow morphology/explanation remains plausible"],
            ["independent evidence inconsistent with illumination/occlusion"],
        )
    elif evidence.shadow_morphology_support is False:
        candidates[ORIGIN_NATURAL_SHADOW_BOUNDARY] = _candidate(
            STATE_FAIL, ["shadow morphology test negative"]
        )
    else:
        candidates[ORIGIN_NATURAL_SHADOW_BOUNDARY] = _candidate(
            STATE_UNRESOLVED, ["shadow morphology not adjudicated"]
        )

    # PHYSICAL_GROUND_FEATURE
    if evidence.independent_ground_feature_binding is True:
        candidates[ORIGIN_PHYSICAL_GROUND_FEATURE] = _candidate(
            STATE_PASS,
            ["independent physical-ground binding"],
        )
    elif evidence.independent_ground_feature_binding is False:
        candidates[ORIGIN_PHYSICAL_GROUND_FEATURE] = _candidate(
            STATE_FAIL, ["independent physical-ground test negative"]
        )
    elif evidence.alternate_basemap_same_boundary is True:
        candidates[ORIGIN_PHYSICAL_GROUND_FEATURE] = _candidate(
            STATE_PROVISIONAL,
            ["boundary persists in an independent basemap; identity still requires ground binding"],
        )
    else:
        candidates[ORIGIN_PHYSICAL_GROUND_FEATURE] = _candidate(
            STATE_UNRESOLVED, ["no independent physical-ground binding"]
        )

    # COMPRESSION / RESAMPLING
    if evidence.compression_or_resampling_support is True:
        candidates[ORIGIN_COMPRESSION_OR_RESAMPLING] = _candidate(
            STATE_PROVISIONAL, ["compression/resampling signature supported"]
        )
    elif evidence.compression_or_resampling_support is False:
        candidates[ORIGIN_COMPRESSION_OR_RESAMPLING] = _candidate(
            STATE_FAIL, ["compression/resampling test negative"]
        )
    else:
        candidates[ORIGIN_COMPRESSION_OR_RESAMPLING] = _candidate(
            STATE_OPEN, ["compression/resampling causation not tested"]
        )

    pass_origins = [name for name, record in candidates.items() if record["state"] == STATE_PASS]
    provisional_origins = [
        name for name, record in candidates.items() if record["state"] == STATE_PROVISIONAL
    ]

    # Zero PASS = not certified. Multiple PASS = contradiction, fail closed.
    resolved_origin = pass_origins[0] if len(pass_origins) == 1 else ORIGIN_UNRESOLVED

    leading_origin_candidate = (
        pass_origins[0]
        if len(pass_origins) == 1
        else provisional_origins[0]
        if len(provisional_origins) == 1
        else ORIGIN_UNRESOLVED
    )

    contradictions: list[str] = []
    if len(pass_origins) > 1:
        contradictions.append("multiple_origin_passes")
    if evidence.source_mosaic_metadata_binding is True and evidence.provider_tile_grid_binding is True:
        contradictions.append("source_mosaic_vs_tile_grid_binding")
    if (
        evidence.independent_ground_feature_binding is True
        and (
            evidence.source_mosaic_metadata_binding is True
            or evidence.provider_tile_grid_binding is True
        )
    ):
        contradictions.append("artifact_vs_physical_ground_binding")
    if evidence.screen_fixed_under_pan is True and evidence.ground_fixed_under_pan is True:
        contradictions.append("screen_fixed_vs_ground_fixed")

    return {
        "observation": _observation_axis(evidence),
        "coordinate_behavior": _coordinate_behavior_axis(evidence),
        "origin_candidates": candidates,
        "resolved_origin": resolved_origin,
        "leading_origin_candidate": leading_origin_candidate,
        "contradictions": contradictions,
    }


def classify_tile_seam(evidence: TileSeamEvidence) -> dict[str, object]:
    """Classify visual seam evidence and attach the causal-origin firewall.

    ``label`` is the legacy visual classification. Consumers MUST use
    ``resolved_origin`` for causal identity and MUST preserve
    ``origin_candidates`` when unresolved.
    """

    positive_flags = [
        evidence.crosses_landcover_classes,
        evidence.persists_across_zoomed_frames,
        evidence.roof_or_object_texture_split,
        evidence.object_anchors_consistent,
    ]
    positive_score = sum(1 for flag in positive_flags if flag)

    contradiction_score = sum(
        1
        for flag in [
            evidence.follows_physical_geometry,
            evidence.shadow_explanation_plausible,
            evidence.raw_coordinate_released,
        ]
        if flag
    )

    origin = classify_seam_origin(evidence)

    if evidence.raw_coordinate_released:
        return {
            "label": TILE_SEAM_INSUFFICIENT,
            "artifact_confidence": "HOLD",
            "ground_feature_confidence": "UNKNOWN",
            "privacy_status": "BLOCK_RAW_COORDINATE_RELEASE",
            "positive_score": positive_score,
            "contradiction_score": contradiction_score,
            **origin,
        }

    if positive_score >= 3 and contradiction_score == 0:
        label = TILE_SEAM_PROBABLE
        artifact_confidence = "MEDIUM_HIGH"
        ground_feature_confidence = "LOW"
    elif positive_score >= 2:
        label = TILE_SEAM_CANDIDATE
        artifact_confidence = "MEDIUM"
        ground_feature_confidence = "LOW_TO_UNKNOWN"
    else:
        label = TILE_SEAM_INSUFFICIENT
        artifact_confidence = "LOW"
        ground_feature_confidence = "UNKNOWN"

    return {
        "label": label,
        "artifact_confidence": artifact_confidence,
        "ground_feature_confidence": ground_feature_confidence,
        "privacy_status": "DERIVED_FIXTURE_ONLY",
        "positive_score": positive_score,
        "contradiction_score": contradiction_score,
        **origin,
    }


def classify_many(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Classify multiple CSV/JSON-style rows."""

    return [classify_tile_seam(evidence_from_mapping(row)) for row in rows]
