"""SATIM visual-analysis calibration engine.

Loads a SATIM ("satellite/screenshot imagery") calibration set
(``data/satim_calibration/<set>/``) and turns the human-marked labels plus the
false-positive scoring rules into adjusted scores and conservative
promotion decisions.

Design posture: this engine is deliberately conservative for public-interest
transparency / research. It *suppresses* likely false positives (palms,
shadows, water, FlightRadar24 3D-render artifacts) and requires cross-source
validation before a marked feature can be "promoted". Outputs are scores and
review flags for a human reviewer; they are never automated assertions about
ground sites. No image pixels are processed -- only the marked labels and the
calibration registry/rule files.

Pure stdlib. YAML parsing reuses ``pipeline.normalize_locations.load_simple_yaml``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.normalize_locations import load_simple_yaml

# Canonical false-positive classes that carry a scoring adjustment. Labels may
# reference other (compound) classes; those get no adjustment and are flagged.
CANONICAL_FALSE_POSITIVE_CLASSES = ("PALM", "SHADOW", "WATER", "FR24_3D_RENDER")

REGISTRY_FILE = "registry_entry.yaml"
MARKER_LEGEND_FILE = "marker_legend.yaml"
FALSE_POSITIVE_FILE = "false_positive_classes.yaml"
LABELS_FILE = "labels.csv"

LABELS_COLUMNS = (
    "image_id",
    "source_page_or_frame",
    "time_local",
    "aircraft",
    "altitude_ft",
    "ground_speed_mph",
    "marker_type",
    "feature_class",
    "false_positive_class",
    "confidence",
    "notes",
)

# Default promotion thresholds, used only if a set omits them.
DEFAULT_PROMOTION_THRESHOLDS = {
    "review": 0.55,
    "cross_source_required": 0.70,
    "promote_to_candidate": 0.80,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MarkerClass:
    marker_type: str
    meaning: str
    satim_role: str
    expected_false_positives: tuple[str, ...]


@dataclass(frozen=True)
class FalsePositiveClass:
    name: str
    description: str
    suppress_when: tuple[str, ...]
    scoring_adjustment: float


@dataclass(frozen=True)
class CalibrationLabel:
    image_id: str
    source_page_or_frame: str
    time_local: str
    aircraft: str
    altitude_ft: int | None
    ground_speed_mph: int | None
    marker_type: str
    feature_class: str
    false_positive_class: str
    confidence: float
    notes: str


@dataclass(frozen=True)
class ScoredLabel:
    image_id: str
    source_page_or_frame: str
    marker_type: str
    feature_class: str
    false_positive_class: str
    raw_confidence: float
    adjustment: float
    adjusted_score: float
    decision: str
    unknown_false_positive_class: bool
    notes: str


@dataclass(frozen=True)
class CalibrationSet:
    set_dir: Path
    calibration_id: str
    evidence_tier: str
    aircraft: dict[str, Any]
    registry: dict[str, Any]
    marker_classes: tuple[MarkerClass, ...]
    false_positive_classes: tuple[FalsePositiveClass, ...]
    promotion_thresholds: dict[str, float]
    labels: tuple[CalibrationLabel, ...]

    @property
    def marker_types(self) -> set[str]:
        return {m.marker_type for m in self.marker_classes}

    @property
    def scoring_adjustments(self) -> dict[str, float]:
        return {fp.name: fp.scoring_adjustment for fp in self.false_positive_classes}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def _to_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return (str(value),)


def parse_marker_classes(marker_legend: dict[str, Any]) -> tuple[MarkerClass, ...]:
    raw = marker_legend.get("marker_classes") or {}
    classes: list[MarkerClass] = []
    for name, body in raw.items():
        body = body or {}
        classes.append(
            MarkerClass(
                marker_type=str(name),
                meaning=str(body.get("meaning", "")),
                satim_role=str(body.get("satim_role", "")),
                expected_false_positives=_as_tuple(body.get("expected_false_positives")),
            )
        )
    return tuple(classes)


def parse_false_positive_classes(
    false_positives: dict[str, Any],
) -> tuple[FalsePositiveClass, ...]:
    definitions = false_positives.get("false_positive_classes") or {}
    adjustments = false_positives.get("scoring_adjustments") or {}
    classes: list[FalsePositiveClass] = []
    for name, body in definitions.items():
        body = body or {}
        classes.append(
            FalsePositiveClass(
                name=str(name),
                description=str(body.get("description", "")),
                suppress_when=_as_tuple(body.get("suppress_when")),
                scoring_adjustment=_to_float(adjustments.get(name), 0.0),
            )
        )
    return tuple(classes)


def load_labels(path: str | Path) -> tuple[CalibrationLabel, ...]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        labels = [
            CalibrationLabel(
                image_id=(row.get("image_id") or "").strip(),
                source_page_or_frame=(row.get("source_page_or_frame") or "").strip(),
                time_local=(row.get("time_local") or "").strip(),
                aircraft=(row.get("aircraft") or "").strip(),
                altitude_ft=_to_int(row.get("altitude_ft")),
                ground_speed_mph=_to_int(row.get("ground_speed_mph")),
                marker_type=(row.get("marker_type") or "").strip(),
                feature_class=(row.get("feature_class") or "").strip(),
                false_positive_class=(row.get("false_positive_class") or "").strip(),
                confidence=_to_float(row.get("confidence"), 0.0),
                notes=(row.get("notes") or "").strip(),
            )
            for row in reader
        ]
    return tuple(labels)


def load_calibration_set(set_dir: str | Path) -> CalibrationSet:
    """Load a single SATIM calibration set directory into a CalibrationSet."""
    set_dir = Path(set_dir)
    registry = load_simple_yaml(set_dir / REGISTRY_FILE)
    marker_legend = load_simple_yaml(set_dir / MARKER_LEGEND_FILE)
    false_positives = load_simple_yaml(set_dir / FALSE_POSITIVE_FILE)
    labels = load_labels(set_dir / LABELS_FILE)

    thresholds_raw = false_positives.get("promotion_thresholds") or DEFAULT_PROMOTION_THRESHOLDS
    thresholds = {key: _to_float(value) for key, value in thresholds_raw.items()}

    return CalibrationSet(
        set_dir=set_dir,
        calibration_id=str(registry.get("registry_id") or false_positives.get("calibration_id") or ""),
        evidence_tier=str(registry.get("evidence_tier", "")),
        aircraft=registry.get("aircraft") or {},
        registry=registry,
        marker_classes=parse_marker_classes(marker_legend),
        false_positive_classes=parse_false_positive_classes(false_positives),
        promotion_thresholds=thresholds,
        labels=labels,
    )


def load_all_calibration_sets(
    root: str | Path = "data/satim_calibration",
) -> list[CalibrationSet]:
    """Discover and load every calibration set under ``root``.

    A set is any subdirectory that contains a ``registry_entry.yaml``.
    """
    root = Path(root)
    sets: list[CalibrationSet] = []
    if not root.exists():
        return sets
    for registry_path in sorted(root.glob(f"*/{REGISTRY_FILE}")):
        sets.append(load_calibration_set(registry_path.parent))
    return sets


# ---------------------------------------------------------------------------
# Scoring + promotion
# ---------------------------------------------------------------------------
def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def promotion_decision(adjusted_score: float, thresholds: dict[str, float]) -> str:
    """Map an adjusted score to a conservative promotion band.

    Bands (defaults): ``candidate`` >= 0.80, ``cross_source_required`` >= 0.70,
    ``review`` >= 0.55, otherwise ``suppressed``. Even a ``candidate`` still
    requires the registry's cross-source / repeatability checks before a human
    promotes it -- this only ranks review priority.
    """
    if adjusted_score >= thresholds.get("promote_to_candidate", 0.80):
        return "candidate"
    if adjusted_score >= thresholds.get("cross_source_required", 0.70):
        return "cross_source_required"
    if adjusted_score >= thresholds.get("review", 0.55):
        return "review"
    return "suppressed"


def score_label(
    label: CalibrationLabel,
    scoring_adjustments: dict[str, float],
    thresholds: dict[str, float],
) -> ScoredLabel:
    """Apply the false-positive scoring adjustment and a promotion decision."""
    fp_class = label.false_positive_class
    unknown = fp_class not in scoring_adjustments
    adjustment = float(scoring_adjustments.get(fp_class, 0.0))
    adjusted = clamp01(label.confidence + adjustment)
    return ScoredLabel(
        image_id=label.image_id,
        source_page_or_frame=label.source_page_or_frame,
        marker_type=label.marker_type,
        feature_class=label.feature_class,
        false_positive_class=fp_class,
        raw_confidence=round(label.confidence, 4),
        adjustment=round(adjustment, 4),
        adjusted_score=round(adjusted, 4),
        decision=promotion_decision(adjusted, thresholds),
        unknown_false_positive_class=unknown,
        notes=label.notes,
    )


def score_calibration_set(calibration_set: CalibrationSet) -> dict[str, Any]:
    """Produce a frontend-ready scored summary for a calibration set."""
    adjustments = calibration_set.scoring_adjustments
    thresholds = calibration_set.promotion_thresholds
    scored = [score_label(lbl, adjustments, thresholds) for lbl in calibration_set.labels]

    decision_breakdown: dict[str, int] = {}
    fp_class_breakdown: dict[str, int] = {}
    non_canonical: dict[str, int] = {}
    for s in scored:
        decision_breakdown[s.decision] = decision_breakdown.get(s.decision, 0) + 1
        fp_class_breakdown[s.false_positive_class] = (
            fp_class_breakdown.get(s.false_positive_class, 0) + 1
        )
        if s.unknown_false_positive_class:
            non_canonical[s.false_positive_class] = (
                non_canonical.get(s.false_positive_class, 0) + 1
            )

    frames = sorted({lbl.source_page_or_frame for lbl in calibration_set.labels})
    raw_scores = [s.raw_confidence for s in scored]
    adj_scores = [s.adjusted_score for s in scored]

    def _mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    warnings: list[str] = []
    if non_canonical:
        detail = ", ".join(f"{name} x{count}" for name, count in sorted(non_canonical.items()))
        warnings.append(
            f"{sum(non_canonical.values())} label(s) use non-canonical "
            f"false_positive_class (no scoring adjustment applied): {detail}"
        )

    return {
        "calibration_id": calibration_set.calibration_id,
        "set_path": str(calibration_set.set_dir).replace("\\", "/"),
        "evidence_tier": calibration_set.evidence_tier,
        "aircraft": calibration_set.aircraft,
        "promotion_thresholds": thresholds,
        "scoring_adjustments": adjustments,
        "counts": {
            "labels": len(scored),
            "frames": len(frames),
            "marker_classes": len(calibration_set.marker_classes),
            "false_positive_classes": len(calibration_set.false_positive_classes),
        },
        "frames": frames,
        "score_summary": {
            "mean_raw": _mean(raw_scores),
            "mean_adjusted": _mean(adj_scores),
            "min_adjusted": min(adj_scores) if adj_scores else 0.0,
            "max_adjusted": max(adj_scores) if adj_scores else 0.0,
        },
        "decision_breakdown": decision_breakdown,
        "fp_class_breakdown": fp_class_breakdown,
        "warnings": warnings,
        "labels": [
            {
                "image_id": s.image_id,
                "frame": s.source_page_or_frame,
                "marker_type": s.marker_type,
                "feature_class": s.feature_class,
                "false_positive_class": s.false_positive_class,
                "raw_confidence": s.raw_confidence,
                "adjustment": s.adjustment,
                "adjusted_score": s.adjusted_score,
                "decision": s.decision,
                "unknown_false_positive_class": s.unknown_false_positive_class,
                "notes": s.notes,
            }
            for s in scored
        ],
    }
