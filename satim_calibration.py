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
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.normalize_locations import load_simple_yaml

SATIM_ENGINE_VERSION = "1.1.0"

# Canonical false-positive classes that carry a scoring adjustment. Labels may
# reference other (compound) classes; those are resolved via false_positive_aliases
# where possible, and otherwise flagged as unknown (no adjustment).
CANONICAL_FALSE_POSITIVE_CLASSES = ("PALM", "SHADOW", "WATER", "FR24_3D_RENDER")

# Resolution status for a label's false_positive_class.
RESOLUTION_RESOLVED = "resolved"  # already a canonical class
RESOLUTION_ALIASED = "aliased"    # mapped to canonical via false_positive_aliases
RESOLUTION_UNKNOWN = "unknown"    # neither canonical nor aliased -> no adjustment

REGISTRY_FILE = "registry_entry.yaml"
MARKER_LEGEND_FILE = "marker_legend.yaml"
FALSE_POSITIVE_FILE = "false_positive_classes.yaml"
LABELS_FILE = "labels.csv"
SOURCE_FILES = (REGISTRY_FILE, MARKER_LEGEND_FILE, FALSE_POSITIVE_FILE, LABELS_FILE)

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
    resolved_false_positive_class: str
    resolution_status: str
    raw_confidence: float
    adjustment: float
    adjusted_score: float
    decision: str
    unknown_false_positive_class: bool
    frame_recurrence: int
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
    false_positive_aliases: dict[str, str]
    promotion_checks: tuple[str, ...]
    required_cross_sources: tuple[str, ...]
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

    aliases_raw = false_positives.get("false_positive_aliases") or {}
    aliases = {str(k): str(v) for k, v in aliases_raw.items()}

    return CalibrationSet(
        set_dir=set_dir,
        calibration_id=str(registry.get("registry_id") or false_positives.get("calibration_id") or ""),
        evidence_tier=str(registry.get("evidence_tier", "")),
        aircraft=registry.get("aircraft") or {},
        registry=registry,
        marker_classes=parse_marker_classes(marker_legend),
        false_positive_classes=parse_false_positive_classes(false_positives),
        false_positive_aliases=aliases,
        promotion_checks=_as_tuple(marker_legend.get("promotion_checks")),
        required_cross_sources=_as_tuple(registry.get("required_cross_source_validation")),
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


def resolve_false_positive_class(
    fp_class: str,
    scoring_adjustments: dict[str, float],
    aliases: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Resolve an observed false_positive_class to a canonical scoring class.

    Returns (resolved_class, resolution_status). A class that is already canonical
    resolves to itself; a compound/observed class is mapped via ``aliases``; an
    unmapped class stays as-is with status ``unknown`` (and gets no adjustment).
    """
    aliases = aliases or {}
    if fp_class in scoring_adjustments:
        return fp_class, RESOLUTION_RESOLVED
    resolved = aliases.get(fp_class)
    if resolved and resolved in scoring_adjustments:
        return resolved, RESOLUTION_ALIASED
    return fp_class, RESOLUTION_UNKNOWN


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
    aliases: dict[str, str] | None = None,
    frame_recurrence: int = 0,
) -> ScoredLabel:
    """Apply the false-positive scoring adjustment and a promotion decision.

    ``frame_recurrence`` is a reported signal (how many distinct frames the
    feature_class appears in); it does not change the adjusted score. This is
    deliberate, not an oversight: recurrence alone doesn't distinguish a real
    feature from a repeating artifact (an FR24 tile seam or a shadow can
    recur across frames just as reliably as a real ground feature), so
    folding it into the score would risk promoting repeat artifacts without
    any actual cross-source evidence. It is surfaced to the reviewer
    (``repeatability`` in ``score_calibration_set``) as one more fact to weigh,
    not as a scoring input.
    """
    original = label.false_positive_class
    resolved, status = resolve_false_positive_class(original, scoring_adjustments, aliases)
    adjustment = float(scoring_adjustments.get(resolved, 0.0))
    adjusted = clamp01(label.confidence + adjustment)
    return ScoredLabel(
        image_id=label.image_id,
        source_page_or_frame=label.source_page_or_frame,
        marker_type=label.marker_type,
        feature_class=label.feature_class,
        false_positive_class=original,
        resolved_false_positive_class=resolved,
        resolution_status=status,
        raw_confidence=round(label.confidence, 4),
        adjustment=round(adjustment, 4),
        adjusted_score=round(adjusted, 4),
        decision=promotion_decision(adjusted, thresholds),
        unknown_false_positive_class=(status == RESOLUTION_UNKNOWN),
        frame_recurrence=frame_recurrence,
        notes=label.notes,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_provenance(calibration_set: CalibrationSet) -> dict[str, Any]:
    """Deterministic provenance: engine version + SHA-256 of each source file."""
    inputs = []
    for filename in SOURCE_FILES:
        path = calibration_set.set_dir / filename
        if path.exists():
            inputs.append({"file": filename, "sha256": _sha256(path)})
    return {"engine_version": SATIM_ENGINE_VERSION, "inputs": inputs}


def frame_recurrence_map(calibration_set: CalibrationSet) -> dict[str, int]:
    """Distinct-frame count per feature_class (frame-to-frame repeatability signal)."""
    frames_by_feature: dict[str, set[str]] = {}
    for lbl in calibration_set.labels:
        frames_by_feature.setdefault(lbl.feature_class, set()).add(lbl.source_page_or_frame)
    return {feature: len(frames) for feature, frames in frames_by_feature.items()}


def score_calibration_set(calibration_set: CalibrationSet) -> dict[str, Any]:
    """Produce a frontend-ready scored summary for a calibration set."""
    adjustments = calibration_set.scoring_adjustments
    thresholds = calibration_set.promotion_thresholds
    aliases = calibration_set.false_positive_aliases
    recurrence = frame_recurrence_map(calibration_set)

    scored = [
        score_label(lbl, adjustments, thresholds, aliases, recurrence.get(lbl.feature_class, 0))
        for lbl in calibration_set.labels
    ]

    decision_breakdown: dict[str, int] = {}
    fp_class_breakdown: dict[str, int] = {}
    resolution_breakdown: dict[str, int] = {}
    non_canonical: dict[str, int] = {}
    for s in scored:
        decision_breakdown[s.decision] = decision_breakdown.get(s.decision, 0) + 1
        fp_class_breakdown[s.false_positive_class] = (
            fp_class_breakdown.get(s.false_positive_class, 0) + 1
        )
        resolution_breakdown[s.resolution_status] = (
            resolution_breakdown.get(s.resolution_status, 0) + 1
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
            f"{sum(non_canonical.values())} label(s) use an unresolved "
            f"false_positive_class (no scoring adjustment applied): {detail}"
        )

    label_rows = [
        {
            "image_id": s.image_id,
            "frame": s.source_page_or_frame,
            "marker_type": s.marker_type,
            "feature_class": s.feature_class,
            "false_positive_class": s.false_positive_class,
            "resolved_false_positive_class": s.resolved_false_positive_class,
            "resolution_status": s.resolution_status,
            "raw_confidence": s.raw_confidence,
            "adjustment": s.adjustment,
            "adjusted_score": s.adjusted_score,
            "decision": s.decision,
            "unknown_false_positive_class": s.unknown_false_positive_class,
            "frame_recurrence": s.frame_recurrence,
            "notes": s.notes,
        }
        for s in scored
    ]

    candidates = [
        {
            "image_id": row["image_id"],
            "frame": row["frame"],
            "marker_type": row["marker_type"],
            "feature_class": row["feature_class"],
            "resolved_false_positive_class": row["resolved_false_positive_class"],
            "adjusted_score": row["adjusted_score"],
            "decision": row["decision"],
            "frame_recurrence": row["frame_recurrence"],
        }
        for row in label_rows
        if row["decision"] != "suppressed"
    ]

    return {
        "calibration_id": calibration_set.calibration_id,
        "set_path": str(calibration_set.set_dir).replace("\\", "/"),
        "evidence_tier": calibration_set.evidence_tier,
        "aircraft": calibration_set.aircraft,
        "promotion_thresholds": thresholds,
        "scoring_adjustments": adjustments,
        "false_positive_aliases": aliases,
        "marker_legend": [
            {
                "marker_type": m.marker_type,
                "meaning": m.meaning,
                "satim_role": m.satim_role,
                "expected_false_positives": list(m.expected_false_positives),
            }
            for m in calibration_set.marker_classes
        ],
        "counts": {
            "labels": len(scored),
            "frames": len(frames),
            "marker_classes": len(calibration_set.marker_classes),
            "false_positive_classes": len(calibration_set.false_positive_classes),
            "candidates": len(candidates),
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
        "resolution_breakdown": resolution_breakdown,
        "repeatability": {
            "by_feature_class": recurrence,
            "recurring_feature_classes": sorted(f for f, c in recurrence.items() if c > 1),
        },
        "promotion_gate": {
            "checks": list(calibration_set.promotion_checks),
            "required_cross_sources": list(calibration_set.required_cross_sources),
            "status": "pending",
            "note": "All gates start pending; a human completes them before promotion.",
        },
        "candidates": candidates,
        "warnings": warnings,
        "provenance": build_provenance(calibration_set),
        "labels": label_rows,
    }
