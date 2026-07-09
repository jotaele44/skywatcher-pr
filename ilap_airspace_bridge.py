"""Backward-compat shim. Logic moved to skywatcher.corrim.ilap_airspace_bridge.
See docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""
from __future__ import annotations

from skywatcher.corrim.ilap_airspace_bridge import (
    CONFIDENCE_WEIGHTS,
    GRID_DEG,
    IDENTITY_NOTE,
    ILAPAirspaceBridge,
    _hydro_utility_score,
    _infra_align_score,
    poi_to_earthgpt_context,
)

__all__ = [
    "CONFIDENCE_WEIGHTS",
    "GRID_DEG",
    "IDENTITY_NOTE",
    "ILAPAirspaceBridge",
    "poi_to_earthgpt_context",
]
