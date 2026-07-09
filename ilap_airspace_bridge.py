"""Backward-compat shim. Logic moved to skywatcher.corrim.ilap_airspace_bridge.
See docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""
from __future__ import annotations

import sys
from pathlib import Path

# "src" is only on sys.path automatically under pytest (pyproject.toml's
# pythonpath setting); bootstrap it here so this shim resolves regardless of
# the calling entry point (see docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md).
_SRC_DIR = Path(__file__).resolve().parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

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
