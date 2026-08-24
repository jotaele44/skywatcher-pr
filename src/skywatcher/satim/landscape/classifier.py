"""Fail-closed agricultural-mosaic candidate classifier for SATIM landscape metrics."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from skywatcher.core.lenses.thresholds import ThresholdRegistry, default_registry

from .benchmark import BenchmarkState
from .extractor import extract_landscape_metrics
from .models import CompetingClassScore, LandscapeAssessment, LandscapeMetrics

SCHEMA_VERSION = "satim.landscape.assessment.v0.1"
METHOD_VERSION = "satim.agricultural_mosaic_classifier.v0.1.0"

THRESHOLD_IDS = (
    "SATIM-LANDSCAPE-FOREST-MATRIX-0.50",
    "SATIM-LANDSCAPE-OPEN-SURFACE-0.10",
    "SATIM-LANDSCAPE-SOIL-FRACTION-0.02",
    "SATIM-LANDSCAPE-BRIGHT-COVER-0.003",
    "SATIM-LANDSCAPE-ROW-TEXTURE-0.25",
    "SATIM-LANDSCAPE-MOSAIC-0.20",
    "SATIM-AGRI-MIN-EVIDENCE-FAMILIES-4",
)

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


def _thresholds(registry: ThresholdRegistry) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    values = {threshold_id: registry.value_of(threshold_id) for threshold_id in THRESHOLD_IDS}
    stamps = tuple(registry.stamp(THRESHOLD_IDS))
    return values, stamps


def _evidence(metrics: LandscapeMetrics, values: dict[str, Any]) -> dict[str, bool]:
    surface_mix = (
        metrics.exposed_soil_fraction >= values["SATIM-LANDSCAPE-SOIL-FRACTION-0.02"]
        or metrics.bright_cover_fraction >= values["SATIM-LANDSCAPE-BRIGHT-COVER-0.003"]
    )
    return {
        "FOREST_MATRIX_CONTEXT": metrics.forest_matrix_fraction
        >= values["SATIM-LANDSCAPE-FOREST-MATRIX-0.50"],
        "MANAGED_OPEN_SURFACE": metrics.open_surface_fraction
        >= values["SATIM-LANDSCAPE-OPEN-SURFACE-0.10"],
        "CULTIVATION_SURFACE_MIX": surface_mix,
        "DIRECTIONAL_ROW_TEXTURE": metrics.directional_texture_score
        >= values["SATIM-LANDSCAPE-ROW-TEXTURE-0.25"],
        "PATCH_MOSAIC_STRUCTURE": metrics.patch_mosaic_score
        >= values["SATIM-LANDSCAPE-MOSAIC-0.20"],
    }


def _rule_score(
    class_name: str,
    evidence: dict[str, bool],
    supports: tuple[str, ...],
    contradictions: tuple[str, ...] = (),
    missing_requirements: tuple[str, ...] = (),
) -> CompetingClassScore:
    supporting = tuple(name for name in supports if evidence.get(name, False))
    contradicting = tuple(name for name in contradictions if evidence.get(name, False))
    if missing_requirements:
        return CompetingClassScore(
            class_name=class_name,
            score=None,
            evaluated=False,
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            unevaluated_requirements=missing_requirements,
        )
    denominator = max(1, len(supports))
    score = max(0.0, (len(supporting) - len(contradicting)) / denominator)
    return CompetingClassScore(
        class_name=class_name,
        score=round(score, 6),
        evaluated=True,
        supporting_evidence=supporting,
        contradicting_evidence=contradicting,
    )


def _competing_scores(
    evidence: dict[str, bool], temporal_recurrence: bool
) -> tuple[CompetingClassScore, ...]:
    agriculture_supports = (
        "FOREST_MATRIX_CONTEXT",
        "MANAGED_OPEN_SURFACE",
        "CULTIVATION_SURFACE_MIX",
        "DIRECTIONAL_ROW_TEXTURE",
        "PATCH_MOSAIC_STRUCTURE",
    )
    agriculture = _rule_score("AGRICULTURAL_MOSAIC", evidence, agriculture_supports)
    if temporal_recurrence and agriculture.score is not None:
        agriculture = CompetingClassScore(
            class_name=agriculture.class_name,
            score=round((len(agriculture.supporting_evidence) + 1) / 6.0, 6),
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
            (),
            ("ARRAY_PANEL_GEOMETRY_OR_MATERIAL_SIGNATURE",),
        ),
    ]
    evaluated_names = {item.class_name for item in scores}
    for class_name in NEGATIVE_CONTROL_CLASSES:
        if class_name in evaluated_names:
            continue
        scores.append(
            CompetingClassScore(
                class_name=class_name,
                score=None,
                evaluated=False,
                unevaluated_requirements=("CLASS_SPECIFIC_NEGATIVE_CONTROL_EXTRACTOR",),
            )
        )
    return tuple(scores)


def classify_metrics(
    metrics: LandscapeMetrics,
    *,
    source_sha256: str,
    source_path: str,
    benchmark: BenchmarkState | None = None,
    temporal_recurrence: bool = False,
    registry: ThresholdRegistry | None = None,
) -> LandscapeAssessment:
    registry = registry or default_registry()
    values, stamps = _thresholds(registry)
    evidence = _evidence(metrics, values)
    competitors = _competing_scores(evidence, temporal_recurrence)

    evaluated = [item for item in competitors if item.evaluated and item.score is not None]
    top_class: str | None = None
    tie = False
    if evaluated:
        top_score = max(float(item.score) for item in evaluated if item.score is not None)
        top = [item for item in evaluated if item.score == top_score]
        tie = len(top) != 1
        if not tie:
            top_class = top[0].class_name

    core_positive_count = sum(evidence.values())
    minimum = int(values["SATIM-AGRI-MIN-EVIDENCE-FAMILIES-4"])
    agriculture_eligible = (
        top_class == "AGRICULTURAL_MOSAIC"
        and core_positive_count >= minimum
        and not tie
    )

    if tie:
        terminal_state = "REVIEW_UNRESOLVED"
    elif agriculture_eligible:
        terminal_state = "CANDIDATE_NOT_IDENTITY"
    else:
        terminal_state = "UNRESOLVED"

    benchmark_state = benchmark.status if benchmark else "NOT_EVALUATED"
    benchmark_blockers = benchmark.blockers if benchmark else (
        "benchmark manifest not supplied; production promotion is fail-closed",
    )
    promotion = bool(benchmark and benchmark.production_promotion_authorized)

    unevaluated_competitors = [item.class_name for item in competitors if not item.evaluated]
    limitations = (
        "Scene-level discovery only; no crop, parcel, ownership, or operator identity is inferred.",
        "Spectral/color evidence alone cannot promote AGRICULTURAL_MOSAIC.",
        "Temporal recurrence never participates in the minimum independent-evidence gate.",
        "Unevaluated negative controls remain UNKNOWN rather than being coerced to zero: "
        + ", ".join(unevaluated_competitors),
        "Production promotion remains blocked until the benchmark denominator passes.",
    )

    return LandscapeAssessment(
        schema_version=SCHEMA_VERSION,
        method_version=METHOD_VERSION,
        source_sha256=source_sha256,
        source_path=source_path,
        metrics=metrics,
        evidence_states=evidence,
        competing_classes=competitors,
        top_class=top_class,
        terminal_state=terminal_state,
        review_required=terminal_state != "UNRESOLVED" or not promotion,
        production_promotion_authorized=promotion,
        thresholds_applied=stamps,
        benchmark_state=benchmark_state,
        benchmark_blockers=benchmark_blockers,
        limitations=limitations,
        temporal_recurrence_support=temporal_recurrence,
    )


def assess_image(
    path: str | Path,
    *,
    benchmark: BenchmarkState | None = None,
    temporal_recurrence: bool = False,
    registry: ThresholdRegistry | None = None,
) -> LandscapeAssessment:
    image_path = Path(path)
    metrics = extract_landscape_metrics(image_path)
    return classify_metrics(
        metrics,
        source_sha256=_sha256(image_path),
        source_path=str(image_path),
        benchmark=benchmark,
        temporal_recurrence=temporal_recurrence,
        registry=registry,
    )
