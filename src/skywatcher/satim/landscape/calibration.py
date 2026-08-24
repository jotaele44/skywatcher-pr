"""Leakage-safe threshold calibration for SATIM agricultural-mosaic recognition.

Thresholds are derived from frozen calibration observations; there are no numeric
fallbacks. A deterministic tie-break may choose serialization order only. It never
changes the epistemic state: tied optimum candidate sets remain a calibration blocker.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

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


def _agricultural_evidence(
    metrics: LandscapeMetrics, thresholds: dict[str, float]
) -> tuple[bool, ...]:
    return (
        metrics.forest_matrix_fraction >= thresholds["forest_matrix_fraction"],
        metrics.open_surface_fraction >= thresholds["open_surface_fraction"],
        (
            metrics.exposed_soil_fraction >= thresholds["exposed_soil_fraction"]
            or metrics.bright_cover_fraction >= thresholds["bright_cover_fraction"]
        ),
        metrics.directional_texture_score
        >= thresholds["directional_texture_score"],
        metrics.patch_mosaic_score >= thresholds["patch_mosaic_score"],
    )


def predicts_agriculture(
    metrics: LandscapeMetrics,
    thresholds: dict[str, float],
    minimum: int,
) -> bool:
    return sum(_agricultural_evidence(metrics, thresholds)) >= minimum


def _midpoints(values: Iterable[float]) -> tuple[float, ...]:
    unique = sorted(set(float(value) for value in values))
    if not unique:
        return ()
    candidates = set(unique)
    for left, right in zip(unique, unique[1:], strict=False):
        candidates.add((left + right) / 2.0)
    return tuple(sorted(candidates))


def _profile_objective(
    records: list[CalibrationRecord],
    thresholds: dict[str, float],
    minimum: int,
) -> tuple[float, ...]:
    tp = fp = tn = fn = 0
    for record in records:
        truth = record.label == "AGRICULTURAL_MOSAIC"
        predicted = predicts_agriculture(record.metrics, thresholds, minimum)
        if truth and predicted:
            tp += 1
        elif truth:
            fn += 1
        elif predicted:
            fp += 1
        else:
            tn += 1

    positive_count = tp + fn
    negative_count = tn + fp
    recall = tp / positive_count if positive_count else 0.0
    specificity = tn / negative_count if negative_count else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    if positive_count and negative_count:
        balanced = (recall + specificity) / 2
    elif positive_count:
        balanced = recall
    else:
        balanced = specificity
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return (
        1.0 if fp == 0 else 0.0,
        recall,
        balanced,
        f1,
        -float(fp),
        float(tn),
    )


def _validate_record_identity(
    records: list[CalibrationRecord],
) -> tuple[str, ...]:
    blockers: list[str] = []
    fixture_ids = [record.fixture_id for record in records]
    hashes = [record.sha256 for record in records]
    if len(fixture_ids) != len(set(fixture_ids)):
        blockers.append("duplicate fixture_id in calibration corpus")
    if len(hashes) != len(set(hashes)):
        blockers.append("duplicate raw-byte SHA256 in calibration corpus")

    calibration_ids = {
        record.fixture_id for record in records if record.split == "CALIBRATION"
    }
    holdout_ids = {
        record.fixture_id for record in records if record.split == "HOLDOUT"
    }
    calibration_hashes = {
        record.sha256 for record in records if record.split == "CALIBRATION"
    }
    holdout_hashes = {
        record.sha256 for record in records if record.split == "HOLDOUT"
    }
    if calibration_ids & holdout_ids:
        blockers.append("calibration/holdout fixture_id leakage")
    if calibration_hashes & holdout_hashes:
        blockers.append("calibration/holdout raw-byte SHA256 leakage")

    unknown_splits = sorted(
        {record.split for record in records} - {"CALIBRATION", "HOLDOUT"}
    )
    if unknown_splits:
        blockers.append("unknown split values: " + ", ".join(unknown_splits))
    return tuple(blockers)


def _positive_only_profile(
    profile_id: str,
    records: list[CalibrationRecord],
    blockers: list[str],
) -> CalibrationProfile:
    positives = [
        record for record in records if record.label == "AGRICULTURAL_MOSAIC"
    ]
    if not positives:
        blockers.append("no agricultural calibration positives")
        return CalibrationProfile(
            profile_id,
            "CALIBRATION_REQUIRED",
            METHOD_VERSION,
            {},
            None,
            blockers=tuple(blockers),
        )

    thresholds = {
        name: min(float(getattr(record.metrics, name)) for record in positives)
        for name in FEATURES
    }
    minimum = 5
    blockers.append(
        "specificity is unmeasured because calibration set has no negative controls"
    )
    return CalibrationProfile(
        profile_id=profile_id,
        status="PROVISIONAL_POSITIVE_ONLY",
        method_version=METHOD_VERSION,
        thresholds=thresholds,
        min_evidence_families=minimum,
        calibration_fixture_ids=tuple(record.fixture_id for record in records),
        calibration_sha256s=tuple(record.sha256 for record in records),
        blockers=tuple(dict.fromkeys(blockers)),
    )


def calibrate_profile(
    profile_id: str,
    records: Iterable[CalibrationRecord],
) -> CalibrationProfile:
    rows = list(records)
    blockers = list(_validate_record_identity(rows))
    calibration = [record for record in rows if record.split == "CALIBRATION"]
    holdout = [record for record in rows if record.split == "HOLDOUT"]

    if not calibration:
        blockers.append("no CALIBRATION records")
        return CalibrationProfile(
            profile_id,
            "CALIBRATION_REQUIRED",
            METHOD_VERSION,
            {},
            None,
            blockers=tuple(blockers),
        )

    labels = {record.label for record in calibration}
    if labels == {"AGRICULTURAL_MOSAIC"}:
        positive_only = _positive_only_profile(
            profile_id,
            calibration,
            blockers,
        )
        return CalibrationProfile(
            profile_id=positive_only.profile_id,
            status=positive_only.status,
            method_version=positive_only.method_version,
            thresholds=positive_only.thresholds,
            min_evidence_families=positive_only.min_evidence_families,
            calibration_fixture_ids=positive_only.calibration_fixture_ids,
            calibration_sha256s=positive_only.calibration_sha256s,
            holdout_fixture_ids=tuple(record.fixture_id for record in holdout),
            holdout_sha256s=tuple(record.sha256 for record in holdout),
            objective=positive_only.objective,
            candidate_count=positive_only.candidate_count,
            tied_best_count=positive_only.tied_best_count,
            blockers=positive_only.blockers,
        )

    positives = [
        record for record in calibration if record.label == "AGRICULTURAL_MOSAIC"
    ]
    negatives = [
        record for record in calibration if record.label != "AGRICULTURAL_MOSAIC"
    ]
    if not positives or not negatives:
        blockers.append(
            "calibration requires both agricultural and negative classes"
        )
        return CalibrationProfile(
            profile_id,
            "CALIBRATION_REQUIRED",
            METHOD_VERSION,
            {},
            None,
            blockers=tuple(blockers),
        )

    candidate_axes = {
        name: _midpoints(
            getattr(record.metrics, name) for record in calibration
        )
        for name in FEATURES
    }
    candidate_count = 1
    for values in candidate_axes.values():
        candidate_count *= max(1, len(values))
    candidate_count *= 5

    if candidate_count > 2_000_000:
        blockers.append(
            "calibration candidate grid too large for exhaustive adjudication: "
            f"{candidate_count}"
        )
        return CalibrationProfile(
            profile_id,
            "CALIBRATION_REQUIRED",
            METHOD_VERSION,
            {},
            None,
            candidate_count=candidate_count,
            blockers=tuple(blockers),
        )

    best_objective: tuple[float, ...] | None = None
    best: list[tuple[dict[str, float], int]] = []
    axes = [candidate_axes[name] for name in FEATURES]
    for combination in itertools.product(*axes):
        thresholds = dict(zip(FEATURES, combination, strict=True))
        for minimum in range(1, 6):
            objective = _profile_objective(
                calibration,
                thresholds,
                minimum,
            )
            if best_objective is None or objective > best_objective:
                best_objective = objective
                best = [(thresholds, minimum)]
            elif objective == best_objective:
                best.append((thresholds, minimum))

    if not best or best_objective is None:
        blockers.append("no calibration candidate produced an objective")
        return CalibrationProfile(
            profile_id,
            "CALIBRATION_REQUIRED",
            METHOD_VERSION,
            {},
            None,
            candidate_count=candidate_count,
            blockers=tuple(blockers),
        )

    tied_best_count = len(best)
    best.sort(
        key=lambda item: (
            item[1],
            tuple(item[0][name] for name in FEATURES),
        ),
        reverse=True,
    )
    thresholds, minimum = best[0]
    if tied_best_count > 1:
        blockers.append(
            "tied calibration optimum set requires review: "
            f"{tied_best_count} candidates"
        )
    status = "CALIBRATED" if not blockers else "CALIBRATION_REQUIRED"
    return CalibrationProfile(
        profile_id=profile_id,
        status=status,
        method_version=METHOD_VERSION,
        thresholds=thresholds,
        min_evidence_families=minimum,
        calibration_fixture_ids=tuple(record.fixture_id for record in calibration),
        calibration_sha256s=tuple(record.sha256 for record in calibration),
        holdout_fixture_ids=tuple(record.fixture_id for record in holdout),
        holdout_sha256s=tuple(record.sha256 for record in holdout),
        objective=best_objective,
        candidate_count=candidate_count,
        tied_best_count=tied_best_count,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def save_calibration_profile(
    profile: CalibrationProfile,
    path: str | Path,
) -> None:
    Path(path).write_text(
        json.dumps(profile.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_calibration_profile(path: str | Path) -> CalibrationProfile:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != "satim.landscape.calibration_profile.v0.1":
        raise ValueError("unsupported calibration profile schema")
    minimum = raw.get("min_evidence_families")
    return CalibrationProfile(
        profile_id=str(raw["profile_id"]),
        status=str(raw["status"]),
        method_version=str(raw["method_version"]),
        thresholds={
            str(key): float(value)
            for key, value in dict(raw.get("thresholds") or {}).items()
        },
        min_evidence_families=int(minimum) if minimum is not None else None,
        calibration_fixture_ids=tuple(raw.get("calibration_fixture_ids") or ()),
        calibration_sha256s=tuple(raw.get("calibration_sha256s") or ()),
        holdout_fixture_ids=tuple(raw.get("holdout_fixture_ids") or ()),
        holdout_sha256s=tuple(raw.get("holdout_sha256s") or ()),
        objective=tuple(float(value) for value in raw.get("objective") or ()),
        candidate_count=int(raw.get("candidate_count") or 0),
        tied_best_count=int(raw.get("tied_best_count") or 0),
        blockers=tuple(raw.get("blockers") or ()),
    )
