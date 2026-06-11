"""Shared MBIL (Municipal Boundary Intelligence Layer) scoring for bridge outputs.

MBIL classifies a lat/lon by proximity to the nearest Puerto Rico municipality:

  MBIL-3  < 5 km   — inside or touching municipality boundary
  MBIL-2  < 10 km  — inner periurban / suburban fringe
  MBIL-1  < 15 km  — outer periurban
  MBIL-0  ≥ 15 km  — rural / remote
  MBIL-X           — off-island or coordinates unavailable

Usage::

    from integration.mbil import mbil_class, mbil_proximity_weight

    cls = mbil_class(lat, lon)          # → 'MBIL-3' | ... | 'MBIL-X'
    w   = mbil_proximity_weight(cls)    # → float in [0, 1]
"""

from __future__ import annotations

import csv
import math
import os
from functools import lru_cache
from typing import List, Optional, Tuple

# Puerto Rico bounding box — a few tenths of a degree margin so coastal points
# don't get clipped (Aguadilla north ~18.53, southwestern Lajas ~17.95).
_PR_LAT_MIN: float = 17.80
_PR_LAT_MAX: float = 18.60
_PR_LON_WEST: float = -67.30
_PR_LON_EAST: float = -65.50

# Full 72-municipality centroid set — same list used by readiness/spiderweb_intake.py.
# Kept in sync here so the producer (integration/) and the consumer (readiness/) share
# identical geometry without introducing a cross-package import.
MUNICIPAL_CENTROIDS: List[Tuple[float, float]] = [
    # Original 20
    (18.4655, -66.1057),  # San Juan
    (18.0099, -66.6140),  # Ponce
    (18.4279, -66.7177),  # Mayagüez
    (18.4906, -67.1414),  # Aguadilla
    (18.3990, -65.9732),  # Carolina
    (18.3449, -66.0498),  # Guaynabo
    (18.3804, -65.8754),  # Loíza
    (18.2218, -66.0370),  # Cayey
    (18.0791, -66.5293),  # Juana Díaz
    (18.2499, -65.8960),  # Humacao
    (18.4735, -66.9008),  # San Germán
    (18.1466, -65.9965),  # Salinas
    (18.3660, -66.4696),  # Barceloneta
    (18.2302, -66.3068),  # Aibonito
    (18.4562, -66.5551),  # Arecibo
    (18.1306, -66.7327),  # Yauco
    (18.4284, -66.1617),  # Bayamón
    (18.4014, -66.2956),  # Toa Baja
    (18.4449, -66.6188),  # Camuy
    (18.3002, -65.6340),  # Fajardo
    # Extended — eastern PR
    (18.2833, -65.9000),  # Caguas
    (18.4667, -65.8333),  # Luquillo
    (18.4000, -65.8833),  # Río Grande
    (18.3606, -65.6268),  # Ceiba
    (18.2333, -65.8167),  # Juncos
    (18.2799, -65.7760),  # Yabucoa
    (18.1167, -65.8833),  # Patillas
    (18.1833, -65.7000),  # Maunabo
    (18.2500, -65.8833),  # Las Piedras
    (18.3167, -65.8333),  # Trujillo Alto
    (18.4500, -65.9833),  # Canóvanas
    (18.2267, -65.9702),  # Gurabo
    (18.3333, -65.7333),  # Las Piedras (alt)
    # Extended — northern coast
    (18.4667, -66.1167),  # Toa Alta
    (18.4167, -66.2500),  # Vega Alta
    (18.4500, -66.3333),  # Vega Baja
    (18.4167, -66.4833),  # Manatí
    (18.4800, -66.7167),  # Quebradillas
    (18.4667, -67.0333),  # Isabela
    (18.5333, -67.0833),  # Aguadilla (north)
    (18.4000, -66.7500),  # Aguada
    (18.3571, -67.1792),  # Moca
    # Extended — central highlands
    (18.3333, -66.8667),  # Lares
    (18.3011, -66.6942),  # Utuado
    (18.3614, -66.9291),  # Las Marías
    (18.3005, -66.9217),  # Maricao
    (18.2833, -66.4833),  # Orocovis
    (18.2500, -66.3333),  # Barranquitas
    (18.1833, -66.2833),  # Comerío
    (18.2000, -66.0333),  # Aguas Buenas
    (18.3333, -65.9833),  # Naranjito
    (18.2000, -66.4833),  # Villalba
    # Extended — western & southwestern PR
    (18.1417, -66.8783),  # Añasco
    (18.0500, -66.8167),  # Hormigueros
    (18.0833, -67.1500),  # Lajas
    (18.0167, -66.8667),  # Cabo Rojo
    (17.9966, -66.6143),  # Guayanilla
    # Extended — southern PR
    (18.0272, -66.3612),  # Santa Isabel
    (17.9667, -66.3833),  # Coamo
    (18.0500, -66.1281),  # Guayama
    (17.9999, -66.1000),  # Arroyo
    (18.1167, -66.3833),  # Juana Díaz (alt)
]

# MBIL class → normalised [0, 1] confidence weight contribution.
_MBIL_WEIGHTS = {
    "MBIL-3": 1.0,
    "MBIL-2": 0.75,
    "MBIL-1": 0.5,
    "MBIL-0": 0.0,
    "MBIL-X": 0.0,
}

# Active centroid set used by mbil_class(). Defaults to the built-in list but can
# be overridden with operator-supplied centroids (T7-60). Kept as a module global
# so the @lru_cache on mbil_class stays valid for the lifetime of a centroid set.
_ACTIVE_CENTROIDS: List[Tuple[float, float]] = list(MUNICIPAL_CENTROIDS)

# Env var: path to a centroid CSV applied at import time (columns: lat, lon).
_CENTROID_CSV_ENV = "SPIDERWEB_CENTROID_CSV"


def load_centroid_csv(csv_path: str) -> List[Tuple[float, float]]:
    """Load ``(lat, lon)`` centroid pairs from a CSV with ``lat``/``lon`` columns.

    Rows with missing or unparseable coordinates are skipped. Raises
    ``ValueError`` if the file yields no usable centroids (a silent empty set
    would make every point classify as MBIL-0).
    """
    centroids: List[Tuple[float, float]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                lat = float(row["lat"])
                lon = float(row["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            centroids.append((lat, lon))
    if not centroids:
        raise ValueError(f"no usable (lat, lon) centroids in {csv_path}")
    return centroids


def set_municipal_centroids(centroids: List[Tuple[float, float]]) -> None:
    """Replace the active centroid set and invalidate the mbil_class cache (T7-60)."""
    global _ACTIVE_CENTROIDS
    if not centroids:
        raise ValueError("centroid set must be non-empty")
    _ACTIVE_CENTROIDS = list(centroids)
    mbil_class.cache_clear()


def reset_municipal_centroids() -> None:
    """Restore the built-in 72-municipality centroid set (T7-60)."""
    set_municipal_centroids(list(MUNICIPAL_CENTROIDS))


def _min_dist_deg(
    lat: float, lon: float, centroids: List[Tuple[float, float]]
) -> float:
    return min(
        math.sqrt((lat - clat) ** 2 + (lon - clon) ** 2) for clat, clon in centroids
    )


@lru_cache(maxsize=4096)
def mbil_class(lat: float, lon: float) -> str:
    """Return the MBIL proximity class for the given point.

    Results are memoized (LRU, 4096 slots) — repeated calls with the same
    coordinates are O(1) after the first lookup.

    Args:
        lat: Latitude in decimal degrees (WGS-84).
        lon: Longitude in decimal degrees (WGS-84).

    Returns:
        One of ``'MBIL-3'``, ``'MBIL-2'``, ``'MBIL-1'``, ``'MBIL-0'``, or
        ``'MBIL-X'`` (off-island / missing coordinates).
    """
    if not (
        isinstance(lat, (int, float))
        and isinstance(lon, (int, float))
        and _PR_LAT_MIN <= lat <= _PR_LAT_MAX
        and _PR_LON_WEST <= lon <= _PR_LON_EAST
    ):
        return "MBIL-X"
    dist_km = _min_dist_deg(lat, lon, _ACTIVE_CENTROIDS) * 111.0
    if dist_km < 5.0:
        return "MBIL-3"
    if dist_km < 10.0:
        return "MBIL-2"
    if dist_km < 15.0:
        return "MBIL-1"
    return "MBIL-0"


def mbil_proximity_weight(cls: str) -> float:
    """Map an MBIL class string to a [0, 1] confidence-weight component."""
    return _MBIL_WEIGHTS.get(cls, 0.0)


def is_mbil_high(cls: str) -> bool:
    """True when the MBIL class is MBIL-2 or MBIL-3 (inner periurban or closer)."""
    return cls in ("MBIL-2", "MBIL-3")


def _apply_env_centroids() -> Optional[str]:
    """Apply the SPIDERWEB_CENTROID_CSV override at import time, if set and readable.

    Returns the path applied, or None. Failures are swallowed (the built-in set
    stays active) so a bad env var never breaks the import.
    """
    path = os.environ.get(_CENTROID_CSV_ENV)
    if not path:
        return None
    try:
        set_municipal_centroids(load_centroid_csv(path))
        return path
    except (OSError, ValueError):
        return None


_apply_env_centroids()
