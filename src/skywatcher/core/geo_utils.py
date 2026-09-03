"""Shared geodesy primitives.

haversine_m is a generic great-circle distance helper used by both SATIM
(satim_geometry.py's parallax/geometry-coherence checks) and FPIM/CORRIM-side
proximity matching (skywatcher.correlation.footprint_proximity). A pure math
function has no domain-specific behavior, so it lives in Core rather than
being owned by (and cross-imported from) either domain module. See
docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lon2 - lon1)
    a = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))
