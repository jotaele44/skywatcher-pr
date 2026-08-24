"""Leakage-safe threshold calibration for SATIM agricultural-mosaic recognition.

Thresholds are derived from frozen calibration observations; there are no numeric
fallbacks. A deterministic tie-break may choose serialization order only. It never
changes the epistemic state: tied optimum candidate sets remain a calibration blocker.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import CalibrationProfile, LandscapeMetrics

METHOD_VERSION = "satim.landscape.calibration.v0.1.0"
FEATURES = (
    "forest_matrix_fraction",
    "open_surface_fraction",
    "exposed_soil_fraction",
    "bright_cover_fraction",
    "directional_texture_score",
    "patch_mosaic_score",
)


@dataclass(frozen=True)
class CalibrationRecord:
    fixture_id: str
    sha256: str
    label: str
    split: str
    metrics: LandscapeMetrics


def _agricultural_evidence(metrics: LandscapeMetrics, thresholds: dict[str, float]) -> tuple[bool, ...]:
    return (
        metrics.forest_matrix_fraction >= thresholds["forest_matrix_fraction"],
        metrics.open_surface_fraction >= thresholds["open_surface_fraction"],
        (
            metrics.exposed_soil_fraction >= thresholds["exposed_soil_fraction"]
            or metrics.bright_cover_fraction >= thresholds["bright_cover_fraction"]
        ),
        metrics.directional_texture_score >= thresholds["directional_texture_score"],
        metrics.patch_mosaic_score >= thresholds["patch_mosaic_score"],
    )


def predicts_agriculture(metrics: LandscapeMetrics, thresholds: dict[str, float], minimum: int) -> bool:
    return sum(_agricultural_evidence(metrics, thresholds)) >= minimum


def _midpoints(values: Iterable[float]) -> tuple[float, ...]:
    unique = sorted(set(float(v) for v in values))
    if not unique:
        return ()
    candidates = set(unique)
    for left, right in zip(unique, unique[1:]):
        candidates.add((left + right) / 2.0)
    return tuple(sorted(candidates))


def _profile_objective(records: list[CalibrationRecord], thresholds: dict[str, float], minimum: int) -> tuple[float, ...]:
    tp = fp = tn = fn = 0
    for record in records:
        truth = record.label == "AGRICULTURAL_MOSAIC"
        pred = predicts_agriculture(record.metrics, thresholds, minimum)
        if truth and pred: tp += 1
        elif truth: fn += 1
        elif pred: fp += 1
        else: tn += 1
    pos = tp + fn
    neg = tn + fp
    recall = tp / pos if pos else 0.0
    specificity = tn / neg if neg else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    balanced = (recall + specificity) / 2 if pos and neg else recall if pos else specificity
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    # Lexicographic maximization. First term enforces zero FP when possible.
    return (1.0 if fp == 0 else 0.0, recall, balanced, f1, -float(fp), float(tn))


def _validate_record_identity(records: list[CalibrationRecord]) -> tuple[str, ...]:
    blockers: list[str] = []
    ids = [r.fixture_id for r in records]
    hashes = [r.sha256 for r in records]
    if len(ids) != len(set(ids)):
        blockers.append("duplicate fixture_id in calibration corpus")
    if len(hashes) != len(set(hashes)):
        blockers.append("duplicate raw-byte SHA256 in calibration corpus")
    cal_ids = {r.fixture_id for r in records if r.split == "CALIBRATION"}
    hold_ids = {r.fixture_id for r in records if r.split == "HOLDOUT"}
    cal_hash = {r.sha256 for r in records if r.split == "CALIBRATION"}
    hold_hash = {r.sha256 for r in records if r.split == "HOLDOUT"}
    if cal_ids & hold_ids:
        blockers.append("calibration/holdout fixture_id leakage")
    if cal_hash & hold_hash:
        blockers.append("calibration/holdout raw-byte SHA256 leakage")
    unknown = sorted({r.split for r in records} - {"CALIBRATION", "HOLDOUT"})
    if unknown:
        blockers.append("unknown split values: " + ", ".join(unknown))
    return tuple(blockers)


def _positive_only_profile(profile_id: str, records: list[CalibrationRecord], blockers: list[str]) -> CalibrationProfile:
    positives = [r for r in records if r.label == "AGRICULTURAL_MOSAIC"]
    if not positives:
        blockers.append("no agricultural calibration positives")
        return CalibrationProfile(profile_id, "CALIBRATION_REQUIRED", METHOD_VERSION, {}, None, blockers=tuple(blockers))
    # Every numeric threshold is empirical: minimum across the positive calibration set.
    thresholds = {name: min(float(getattr(r.metrics, name)) for r in positives) for name in FEATURES}
    # There are five independent evidence families because soil and bright cover are OR-combined.
    minimum = 5
    blockers.append("specificity is unmeasured because calibration set has no negative controls")
    return CalibrationProfile(
        profile_id=profile_id,
        status="PROVISIONAL_POSITIVE_ONLY",
        method_version=METHOD_VERSION,
        thresholds=thresholds,
        min_evidence_families=minimum,
        calibration_fixture_ids=tuple(r.fixture_id for r in records),
        calibration_sha256s=tuple(r.sha256 for r in records),
        blockers=tuple(dict.fromkeys(blockers)),
    )


def calibrate_profile(profile_id: str, records: Iterable[CalibrationRecord]) -> CalibrationProfile:
    rows = list(records)
    blockers = list(_validate_record_identity(rows))
    calibration = [r for r in rows if r.split == "CALIBRATION"]
    holdout = [r for r in rows if r.split == "HOLDOUT"]
    if not calibration:
        blockers.append("no CALIBRATION records")
        return CalibrationProfile(profile_id, "CALIBRATION_REQUIRED", METHOD_VERSION, {}, None, blockers=tuple(blockers))
    labels = {r.label for r in calibration}
    if labels == {"AGRICULTURAL_MOSAIC"}:
        p = _positive_only_profile(profile_id, calibration, blockers)
        return CalibrationProfile(
            **{**p.__dict__, "holdout_fixture_ids": tuple(r.fixture_id for r in holdout), "holdout_sha256s": tuple(r.sha256 for r in holdout)}
        )
    positives = [r for r in calibration if r.label == "AGRICULTURAL_MOSAIC"]
    negatives = [r for r in calibration if r.label != "AGRICULTURAL_MOSAIC"]
    if not positives or not negatives:
        blockers.append("calibration requires both agricultural and negative classes")
        return CalibrationProfile(profile_id, "CALIBRATION_REQUIRED", METHOD_VERSION, {}, None, blockers=tuple(blockers))

    candidate_axes = {name: _midpoints(getattr(r.metrics, name) for r in calibration) for name in FEATURES}
    candidate_count = 1
    for values in candidate_axes.values(): candidate_count *= max(1, len(values))
    candidate_count *= 5

    # Exhaustive search is acceptable for the small benchmark denominator. To bound explosion,
    # fail closed instead of silently sampling a huge parameter space.
    if candidate_count > 2_000_000:
        blockers.append(f"calibration candidate grid too large for exhaustive adjudication: {candidate_count}")
        return CalibrationProfile(profile_id, "CALIBRATION_REQUIRED", METHOD_VERSION, {}, None, candidate_count=candidate_count, blockers=tuple(blockers))

    best_obj: tuple[float, ...] | None = None
    best: list[tuple[dict[str, float], int]] = []
    axes = [candidate_axes[name] for name in FEATURES]
    for combo in itertools.product(*axes):
        thresholds = dict(zip(FEATURES, combo, strict=True))
        for minimum in range(1, 6):
            objective = _profile_objective(calibration, thresholds, minimum)
            if best_obj is None or objective > best_obj:
                best_obj = objective
                best = [(thresholds, minimum)]
            elif objective == best_obj:
                best.append((thresholds, minimum))

    if not best or best_obj is None:
        blockers.append("no calibration candidate produced an objective")
        return CalibrationProfile(profile_id, "CALIBRATION_REQUIRED", METHOD_VERSION, {}, None, candidate_count=candidate_count, blockers=tuple(blockers))

    tied_best_count = len(best)
    # Deterministic serialization only; a tied optimum remains OPEN evidence-wise.
    best.sort(key=lambda item: (item[1], tuple(item[0][name] for name in FEATURES)), reverse=True)
    thresholds, minimum = best[0]
    if tied_best_count > 1:
        blockers.append(f"tied calibration optimum set requires review: {tied_best_count} candidates")
    status = "CALIBRATED" if not blockers else "CALIBRATION_REQUIRED"
    return CalibrationProfile(
        profile_id=profile_id, status=status, method_version=METHOD_VERSION,
        thresholds=thresholds, min_evidence_families=minimum,
        calibration_fixture_ids=tuple(r.fixture_id for r in calibration),
        calibration_sha256s=tuple(r.sha256 for r in calibration),
        holdout_fixture_ids=tuple(r.fixture_id for r in holdout),
        holdout_sha256s=tuple(r.sha256 for r in holdout),
        objective=best_obj, candidate_count=candidate_count, tied_best_count=tied_best_count,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def save_calibration_profile(profile: CalibrationProfile, path: str | Path) -> None:
    Path(path).write_text(json.dumps(profile.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_calibration_profile(path: str | Path) -> CalibrationProfile:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != "satim.landscape.calibration_profile.v0.1":
        raise ValueError("unsupported calibration profile schema")
    return CalibrationProfile(
        profile_id=str(raw["profile_id"]), status=str(raw["status"]), method_version=str(raw["method_version"]),
        thresholds={str(k): float(v) for k, v in dict(raw.get("thresholds") or {}).items()},
        min_evidence_families=(int(raw["min_evidence_families"]) if raw.get("min_evidence_families") is not None else None),
        calibration_fixture_ids=tuple(raw.get("calibration_fixture_ids") or ()),
        calibration_sha256s=tuple(raw.get("calibration_sha256s") or ()),
        holdout_fixture_ids=tuple(raw.get("holdout_fixture_ids") or ()),
        holdout_sha256s=tuple(raw.get("holdout_sha256s") or ()),
        objective=tuple(float(v) for v in raw.get("objective") or ()), candidate_count=int(raw.get("candidate_count") or 0),
        tied_best_count=int(raw.get("tied_best_count") or 0), blockers=tuple(raw.get("blockers") or ()),
    )
