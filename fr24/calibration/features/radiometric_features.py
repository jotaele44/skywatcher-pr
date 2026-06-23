"""L1 radiometric features for SATIM synthetic boundary candidates."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any, Mapping

from .boundary_geometry import as_float, clamp01


@dataclass(frozen=True)
class RadiometricFeatures:
    radiometric_delta: float
    left_mean: float
    right_mean: float
    pooled_std: float


def contrast_score(left_mean: float, right_mean: float, left_std: float, right_std: float) -> float:
    """Normalize cross-boundary contrast by pooled local variation."""
    pooled = sqrt(max(left_std, 0.0) ** 2 + max(right_std, 0.0) ** 2) / sqrt(2.0)
    if pooled <= 0:
        return clamp01(abs(left_mean - right_mean))
    return clamp01(abs(left_mean - right_mean) / (pooled * 3.0))


def compute_radiometric_features(row: Mapping[str, Any]) -> RadiometricFeatures:
    if "radiometric_delta" in row:
        score = clamp01(as_float(row.get("radiometric_delta")))
        return RadiometricFeatures(
            radiometric_delta=score,
            left_mean=as_float(row.get("left_mean")),
            right_mean=as_float(row.get("right_mean")),
            pooled_std=as_float(row.get("pooled_std")),
        )

    legacy = row.get("radiometric_discontinuity_score")
    if legacy not in (None, ""):
        return RadiometricFeatures(
            radiometric_delta=clamp01(as_float(legacy)),
            left_mean=as_float(row.get("left_mean")),
            right_mean=as_float(row.get("right_mean")),
            pooled_std=as_float(row.get("pooled_std")),
        )

    left_mean = as_float(row.get("left_mean"))
    right_mean = as_float(row.get("right_mean"))
    left_std = as_float(row.get("left_std"), 0.1)
    right_std = as_float(row.get("right_std"), 0.1)
    pooled = sqrt(max(left_std, 0.0) ** 2 + max(right_std, 0.0) ** 2) / sqrt(2.0)
    return RadiometricFeatures(
        radiometric_delta=contrast_score(left_mean, right_mean, left_std, right_std),
        left_mean=left_mean,
        right_mean=right_mean,
        pooled_std=pooled,
    )
