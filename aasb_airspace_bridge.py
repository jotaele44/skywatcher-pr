"""Backward-compat shim. Logic moved to skywatcher.corrim.aasb_airspace_bridge.
See docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""
from __future__ import annotations

from skywatcher.corrim.aasb_airspace_bridge import (
    AASBAirspaceBridge,
    AIRPORT_COORDS,
    EDGE_FIELDNAMES,
)

__all__ = [
    "AASBAirspaceBridge",
    "AIRPORT_COORDS",
    "EDGE_FIELDNAMES",
]
