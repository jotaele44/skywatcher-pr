"""Backward-compat shim. Logic moved to skywatcher.corrim.ilap_airspace_bridge.
See docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""
from __future__ import annotations

from skywatcher.corrim.ilap_airspace_bridge import (
    CONFIDENCE_WEIGHTS,
    GRID_DEG,
    IDENTITY_NOTE,
    ILAPAirspaceBridge,
    # Underscore-prefixed helpers are re-exported deliberately: this module is a
    # backward-compat shim, so narrowing its import surface is a behavior change,
    # not a cleanup. tests/test_ilap_bridge.py imports _infra_align_score from
    # here. They are absent from __all__ because they are private, which is why
    # ruff cannot see them as re-exports.
    _hydro_utility_score,  # noqa: F401
    _infra_align_score,  # noqa: F401
    poi_to_earthgpt_context,
)

__all__ = [
    "CONFIDENCE_WEIGHTS",
    "GRID_DEG",
    "IDENTITY_NOTE",
    "ILAPAirspaceBridge",
    "poi_to_earthgpt_context",
]
