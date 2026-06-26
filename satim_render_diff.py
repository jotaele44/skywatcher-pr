"""Synthetic render-diff auto-labeling for FR24_3D_RENDER artifacts.

Corpus expansion without human marking. The same ground coordinates are
re-rendered at varied zoom / level-of-detail / oblique angle; a feature whose
presence *changes* with render parameters exists only in the renderer, not on the
ground, and is an ``FR24_3D_RENDER`` false positive by construction. A feature
present under every parameter set is render-invariant and is not auto-labeled.

This module is the pure classification logic; the renderer that produces the
per-parameter presence observations lives outside the repo (network/asset-gated),
so callers feed it observation tuples (e.g. from a cached render sweep).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

RENDER_FP_CLASS = "FR24_3D_RENDER"


def classify_render_diff(presence_by_params: Mapping[str, bool]) -> str | None:
    """Return ``FR24_3D_RENDER`` if a feature's presence varies across params.

    ``None`` when presence is constant (always or never present) — render-invariant
    features are not auto-labeled as artifacts.
    """
    values = [bool(v) for v in presence_by_params.values()]
    if len(values) < 2:
        return None
    if any(values) and not all(values):
        return RENDER_FP_CLASS
    return None


def _presence_fraction(presence_by_params: Mapping[str, bool]) -> float:
    values = [bool(v) for v in presence_by_params.values()]
    return sum(values) / len(values) if values else 0.0


def autolabel_render_diff(
    observations: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Auto-label render-dependent features as FR24_3D_RENDER false positives.

    ``observations`` are ``{feature_id, param_set, present[, image_id]}`` rows
    (one per render parameter set). Returns ground-truth rows (``is_false_positive``
    = ``1``) for features whose presence varies with render parameters.
    """
    presence: dict[str, dict[str, bool]] = defaultdict(dict)
    image_ids: dict[str, str] = {}
    for obs in observations:
        feature_id = str(obs.get("feature_id", "")).strip()
        if not feature_id:
            continue
        param_set = str(obs.get("param_set", "")).strip()
        present = str(obs.get("present", "")).strip().lower() in ("1", "true", "yes")
        presence[feature_id][param_set] = present
        image_ids.setdefault(feature_id, str(obs.get("image_id", feature_id)))

    rows: list[dict[str, str]] = []
    for feature_id, by_params in presence.items():
        if classify_render_diff(by_params) is None:
            continue
        rows.append(
            {
                "image_id": image_ids.get(feature_id, feature_id),
                "false_positive_class": RENDER_FP_CLASS,
                "confidence": f"{_presence_fraction(by_params):.4f}",
                "is_false_positive": "1",
                "source": "render_diff",
            }
        )
    return rows
