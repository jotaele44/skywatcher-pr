"""Fail-closed agricultural-mosaic candidate classifier for SATIM landscape metrics."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .benchmark import BenchmarkState
from .calibration import FEATURES
from .extractor import extract_landscape_metrics
from .models import (
    CalibrationProfile,
    CompetingClassScore,
    LandscapeAssessment,
    LandscapeMetrics,
)

SCHEMA_VERSION = "satim.landscape.assessment.v0.2"
METHOD_VERSION = "satim.agricultural_mosaic_classifier.v0.2.0"
NEGATIVE_CONTROL_CLASSES = (
    "LANDSLIDE_OR_SCARP",
    "CONSTRUCTION_GRADING",
    "UTILITY_CORRIDOR",
    "ROAD_CUT",
    "QUARRY_OR_BORROW",
    "EXPOSED_RIVER_SEDIMENT",
    "HURRICANE_BLOWDOWN",
    "SOLAR_ARRAY",
    "LOGGING_CLEARING",
    "ABANDONED_BUILDING_PAD",
    "PASTURE_OR_LAWN",
    "NATURAL_SPARSE_VEGETATION",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence(
    metrics: LandscapeMetrics,
    profile: CalibrationProfile | None,
) -> dict[str, bool | None]:
    evidence_names = (
        "FOREST_MATRIX_CONTEXT",
        "MANAGED_OPEN_SURFACE",
        "CULTIVATION_SURFACE_MIX",
        "DIRECTIONAL_ROW_TEXTURE",
        "PATCH_MOSAIC_STRUCTURE",
    )
    if (
        profile is None
        or not profile.usable
        or any(name not in profile.thresholds for name in FEATURES)
    ):
        return dict.fromkeys(evidence_names)

    thresholds = profile.thresholds
    return {
        "FOREST_MATRIX_CONTEXT": metrics.forest_matrix_fraction
        >= thresholds["forest_matrix_fraction"],
        "MANAGED_OPEN_SURFACE": metrics.open_surface_fraction
        >= thresholds["open_surface_fraction"],
        "CULTIVATION_SURFACE_MIX": (
            metrics.exposed_soil_fraction
            >= thresholds["exposed_soil_fraction"]
            or metrics.bright_cover_fraction
            >= thresholds["bright_cover_fraction"]
        ),
        "DIRECTIONAL_ROW_TEXTURE": metrics.directional_texture_score
        >= thresholds["directional_texture_score"],
        "PATCH_MOSAIC_STRUCTURE": metrics.patch_mosaic_score
        >= thresholds["patch_mosaic_score"],
    }


def _rule_score(
    class_name: str,
    evidence: dict[str, bool | None],
    supports: tuple[str, ...],
    contradictions: tuple[str, ...] = (),
    missing_requirements: tuple[str, ...] = (),
) -> CompetingClassScore:
    unknown = tuple(
        name
        for name in supports + contradictions
        if evidence.get(name) is None
    )
    missing = tuple(dict.fromkeys(missing_requirements + unknown))
    supporting = tuple(
        name for name in supports if evidence.get(name) is True
    )
    contradicting = tuple(
        name for name in contradictions if evidence.get(name) is True
    )
    if missing:
        return CompetingClassScore(
            class_name=class_name,
            score=None,
            evaluated=False,
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            unevaluated_requirements=missing,
        )

    denominator = max(1, len(supports))
    score = max(
        0.0,
        (len(supporting) - len(contradicting)) / denominator,
    )
    return CompetingClassScore(
        class_name=class_name,
        score=round(score, 6),
        evaluated=True,
        supporting_evidence=supporting,
        contradicting_evidence=contradicting,
    )


def _competing_scores(
    evidence: dict[str, bool | None],
    temporal_recurrence: bool,
) -> tuple[CompetingClassScore, ...]:
    agriculture_supports = (
        "FOREST_MATRIX_CONTEXT",
        "MANAGED_OPEN_SURFACE",
        "CULTIVATION_SURFACE_MIX",
        "DIRECTIONAL_ROW_TEXTURE",
        "PATCH_MOSAIC_STRUCTURE",
    )
    agriculture = _rule_score(
        "AGRICULTURAL_MOSAIC",
        evidence,
        agriculture_supports,
    )
    if temporal_recurrence and agriculture.score is not None:
        agriculture = CompetingClassScore(
            class_name=agriculture.class_name,
            score=round(
                (len(agriculture.supporting_evidence) + 1) / 6.0,
                6,
            ),
            evaluated=True,
            supporting_evidence=agriculture.supporting_evidence
            + ("TEMPORAL_CULTIVATION_RECURRENCE",),
            contradicting_evidence=agriculture.contradicting_evidence,
        )

    scores = [
        agriculture,
        _rule_score(
            "PASTURE_OR_LAWN",
            evidence,
            ("FOREST_MATRIX_CONTEXT", "MANAGED_OPEN_SURFACE"),
            ("CULTIVATION_SURFACE_MIX", "DIRECTIONAL_ROW_TEXTURE"),
        ),
        _rule_score(
            "CONSTRUCTION_GRADING",
            evidence,
            ("MANAGED_OPEN_SURFACE", "CULTIVATION_SURFACE_MIX"),
            ("DIRECTIONAL_ROW_TEXTURE",),
        ),
        _rule_score(
            "LANDSLIDE_OR_SCARP",
            evidence,
            ("MANAGED_OPEN_SURFACE", "CULTIVATION_SURFACE_MIX"),
            ("DIRECTIONAL_ROW_TEXTURE",),
        ),
        _rule_score(
            "QUARRY_OR_BORROW",
            evidence,
            ("MANAGED_OPEN_SURFACE", "CULTIVATION_SURFACE_MIX"),
            ("DIRECTIONAL_ROW_TEXTURE",),
            ("BENCH_OR_HIGHWALL_GEOMETRY",),
        ),
        _rule_score(
            "SOLAR_ARRAY",
            evidence,
            ("DIRECTIONAL_ROW_TEXTURE",),
            missing_requirements=(
                "ARRAY_PANEL_GEOMETRY_OR_MATERIAL_SIGNATURE",
            ),
        ),
    ]
    evaluated_names = {score.class_name for score in scores}
    for class_name in NEGATIVE_CONTROL_CLASSES:
        if class_name in evaluated_names:
            continue
        scores.append(
            CompetingClassScore(
                class_name=class_name,
                score=None,
                evaluated=False,
                unevaluated_requirements=(
                    "CLASS_SPECIFIC_NEGATIVE_CONTROL_EXTRACTOR",
                ),
            )
        )
    return tuple(scores)


def classify_metrics(
    metrics: LandscapeMetrics,
    *,
    source_sha256: str,
    source_path: str,
    calibration: CalibrationProfile | None = None,
    benchmark: BenchmarkState | None = None,
    temporal_recurrence: bool = False,
) -> LandscapeAssessment:
    evidence = _evidence(metrics, calibration)
    competitors = _competing_scores(evidence, temporal_recurrence)
    core_count = sum(value is True for value in evidence.values())

    evaluated = [
        item
        for item in competitors
        if item.evaluated and item.score is not None
    ]
    top_class: str | None = None
    tie = False
    if evaluated:
        top_score = max(float(item.score) for item in evaluated)
        top = [item for item in evaluated if item.score == top_score]
        tie = len(top) != 1
        if not tie:
            top_class = top[0].class_name

    minimum = (
        calibration.min_evidence_families
        if calibration is not None and calibration.usable
        else None
    )
    eligible = bool(
        top_class == "AGRICULTURAL_MOSAIC"
        and minimum is not None
        and core_count >= minimum
        and not tie
    )

    if tie:
        terminal = "REVIEW_UNRESOLVED"
    elif eligible:
        terminal = "CANDIDATE_NOT_IDENTITY"
    else:
        terminal = "UNRESOLVED"

    benchmark_state = benchmark.status if benchmark else "NOT_EVALUATED"
    benchmark_blockers = (
        benchmark.blockers
        if benchmark
        else ("benchmark not supplied; production promotion is fail-closed",)
    )
    calibration_status = (
        calibration.status if calibration else "CALIBRATION_REQUIRED"
    )
    promotion = bool(
        calibration
        and calibration.production_validated
        and benchmark
        and benchmark.production_promotion_authorized
    )

    unevaluated_competitors = [
        item.class_name for item in competitors if not item.evaluated
    ]
    limitations = (
        "Scene/field morphology only; no crop, parcel, ownership, operator, mission, "
        "or legal land-use identity is inferred.",
        "COLOR_ONLY, CLEARING_ONLY, and RECTANGLE_ONLY cannot promote "
        "AGRICULTURAL_MOSAIC.",
        "Temporal recurrence is supplementary and never participates in the "
        "independent-evidence minimum.",
        "Unevaluated competitors remain NULL/UNKNOWN: "
        + ", ".join(unevaluated_competitors),
        "Production promotion requires a VALIDATED calibration profile and PASS "
        "benchmark.",
    )

    return LandscapeAssessment(
        schema_version=SCHEMA_VERSION,
        method_version=METHOD_VERSION,
        source_sha256=source_sha256,
        source_path=source_path,
        metrics=metrics,
        evidence_states=evidence,
        independent_positive_evidence_count=core_count,
        competing_classes=competitors,
        top_class=top_class,
        terminal_state=terminal,
        review_required=terminal == "REVIEW_UNRESOLVED" or not promotion,
        production_promotion_authorized=promotion,
        thresholds_applied=(
            calibration.stamps()
            if calibration is not None and calibration.usable
            else ()
        ),
        calibration_profile_id=(
            calibration.profile_id if calibration is not None else None
        ),
        calibration_status=calibration_status,
        benchmark_state=benchmark_state,
        benchmark_blockers=benchmark_blockers,
        limitations=limitations,
        temporal_recurrence_support=temporal_recurrence,
    )


def assess_image(
    path: str | Path,
    *,
    calibration: CalibrationProfile | None = None,
    benchmark: BenchmarkState | None = None,
    temporal_recurrence: bool = False,
) -> LandscapeAssessment:
    image_path = Path(path)
    return classify_metrics(
        extract_landscape_metrics(image_path),
        source_sha256=_sha256(image_path),
        source_path=str(image_path),
        calibration=calibration,
        benchmark=benchmark,
        temporal_recurrence=temporal_recurrence,
    )
