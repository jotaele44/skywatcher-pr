"""Empirical re-fitting of SATIM calibration constants.

Given a labeled ``ground_truth.csv`` (see :mod:`satim_ground_truth`), derive
``scoring_adjustments`` and ``promotion_thresholds`` from measured true-positive /
false-positive outcomes instead of the hand-picked v1 values. The result is emitted
as a *new* versioned set so v1 is never overwritten and ``scripts/validate_satim_calibration.py``
can vet it.

Method, kept deliberately transparent (no external stats dependency):

* **scoring_adjustments** — per canonical class, the additive shift that moves the
  class's mean marked confidence onto its empirical precision, clamped to ``[-1, 0]``
  (the validator's suppressive range). A class whose marks are mostly artifacts but
  were drawn confidently gets a strong negative shift; a mostly-real class gets ~0.
* **promotion_thresholds** — the lowest adjusted-confidence cut at which the retained
  set reaches a target precision, swept for review / cross-source / promote targets
  and forced monotonic.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from satim_calibration import CANONICAL_FALSE_POSITIVE_CLASSES

# Precision each promotion band must clear, low -> high.
DEFAULT_PRECISION_TARGETS = {
    "review": 0.50,
    "cross_source_required": 0.75,
    "promote_to_candidate": 0.90,
}
THRESHOLD_ORDER = ("review", "cross_source_required", "promote_to_candidate")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class ClassStats:
    fp_class: str
    n: int
    n_true: int
    mean_confidence: float

    @property
    def precision(self) -> float:
        return self.n_true / self.n if self.n else 0.0


@dataclass(frozen=True)
class FitResult:
    scoring_adjustments: dict[str, float]
    promotion_thresholds: dict[str, float]
    n_rows: int
    class_stats: dict[str, ClassStats] = field(default_factory=dict)


def _parse_rows(rows: Iterable[Mapping[str, Any]]) -> list[tuple[str, float, bool]]:
    """Return ``(canonical_class, confidence, is_real)`` tuples for clean rows."""
    parsed: list[tuple[str, float, bool]] = []
    for row in rows:
        fp = str(row.get("false_positive_class") or "").strip().upper()
        if fp not in CANONICAL_FALSE_POSITIVE_CLASSES:
            continue
        try:
            confidence = float(row.get("confidence"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        flag = str(row.get("is_false_positive", "")).strip().lower()
        if flag in ("1", "true", "yes", "fp"):
            is_real = False
        elif flag in ("0", "false", "no", "tp"):
            is_real = True
        else:
            continue
        parsed.append((fp, confidence, is_real))
    return parsed


def fit_scoring_adjustments(
    parsed: Sequence[tuple[str, float, bool]],
) -> tuple[dict[str, float], dict[str, ClassStats]]:
    adjustments: dict[str, float] = {}
    stats: dict[str, ClassStats] = {}
    for fp_class in CANONICAL_FALSE_POSITIVE_CLASSES:
        rows = [(c, real) for cls, c, real in parsed if cls == fp_class]
        if not rows:
            adjustments[fp_class] = 0.0
            continue
        n = len(rows)
        n_true = sum(1 for _, real in rows if real)
        mean_conf = sum(c for c, _ in rows) / n
        precision = n_true / n
        adjustments[fp_class] = round(_clamp(precision - mean_conf, -1.0, 0.0), 4)
        stats[fp_class] = ClassStats(fp_class, n, n_true, round(mean_conf, 4))
    return adjustments, stats


def _precision_at(cut: float, scored: Sequence[tuple[float, bool]]) -> tuple[float, int]:
    retained = [real for adj, real in scored if adj >= cut]
    if not retained:
        return 0.0, 0
    return sum(1 for r in retained if r) / len(retained), len(retained)


def fit_promotion_thresholds(
    parsed: Sequence[tuple[str, float, bool]],
    adjustments: Mapping[str, float],
    precision_targets: Mapping[str, float] | None = None,
) -> dict[str, float]:
    targets = dict(precision_targets or DEFAULT_PRECISION_TARGETS)
    if not parsed:
        return {"review": 0.55, "cross_source_required": 0.70, "promote_to_candidate": 0.80}

    scored = [
        (_clamp(conf + adjustments.get(cls, 0.0), 0.0, 1.0), real)
        for cls, conf, real in parsed
    ]
    cuts = sorted({round(adj, 4) for adj, _ in scored})

    thresholds: dict[str, float] = {}
    running = 0.0
    for band in THRESHOLD_ORDER:
        target = targets[band]
        chosen = cuts[-1]  # most conservative if the target is never met
        for cut in cuts:
            precision, retained = _precision_at(cut, scored)
            if retained and precision >= target:
                chosen = cut
                break
        running = max(running, chosen)
        thresholds[band] = round(_clamp(running, 0.0, 1.0), 4)
    return thresholds


def fit_calibration(
    rows: Iterable[Mapping[str, Any]],
    precision_targets: Mapping[str, float] | None = None,
) -> FitResult:
    """Fit scoring adjustments and promotion thresholds from labeled outcomes."""
    parsed = _parse_rows(rows)
    adjustments, stats = fit_scoring_adjustments(parsed)
    thresholds = fit_promotion_thresholds(parsed, adjustments, precision_targets)
    return FitResult(
        scoring_adjustments=adjustments,
        promotion_thresholds=thresholds,
        n_rows=len(parsed),
        class_stats=stats,
    )


def _leading_key(line: str) -> str | None:
    """Top-level YAML key on a line (no indentation), else None."""
    if not line or line[0] in " #\t":
        return None
    if ":" in line:
        return line.split(":", 1)[0].strip()
    return None


def emit_fp_classes_yaml(
    original_text: str,
    calibration_id: str,
    scoring: Mapping[str, float],
    thresholds: Mapping[str, float],
) -> str:
    """Rewrite a ``false_positive_classes.yaml`` with refitted constants.

    Replaces only the ``scoring_adjustments`` and ``promotion_thresholds`` blocks
    and the ``calibration_id`` line; every other top-level section — the
    descriptive ``false_positive_classes`` block and any ``false_positive_aliases``
    — is preserved verbatim, so the emitted set still satisfies the validator's
    alias and structure checks.
    """
    out: list[str] = []
    skipping_section = False
    for line in original_text.splitlines():
        key = _leading_key(line)
        if key is not None:
            skipping_section = False  # left any block we were rewriting
            if key == "calibration_id":
                out.append(f"calibration_id: {calibration_id}")
                continue
            if key == "scoring_adjustments":
                out.append("scoring_adjustments:")
                for fp_class in CANONICAL_FALSE_POSITIVE_CLASSES:
                    out.append(f"  {fp_class}: {scoring.get(fp_class, 0.0)}")
                skipping_section = True
                continue
            if key == "promotion_thresholds":
                out.append("promotion_thresholds:")
                for band in THRESHOLD_ORDER:
                    out.append(f"  {band}: {thresholds[band]}")
                skipping_section = True
                continue
        if skipping_section:
            continue  # drop the original body of a rewritten block
        out.append(line)
    return "\n".join(out) + "\n"
