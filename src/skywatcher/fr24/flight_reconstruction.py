"""FLIGHT RECONSTRUCTION (mission responsibilities 9, 10, 11)

Reconstructs flights from per-screenshot observations: groups same-aircraft
frames into a flight (association), fuses them into a single flight record
(reconstruction), resolves origin/destination endpoints, and builds ordered
track points.

Wraps the existing FPIM-bucket implementations (``fr24.flight_fusion``,
``fr24.endpoint_matcher``, ``fr24.wave_validator``); all are pure stdlib and
safe to import eagerly. Track-point sampling is delegated to
``fr24.event_export`` lazily (it touches SQLite helpers) to keep imports light.
"""

from __future__ import annotations

from typing import List

from fr24.endpoint_matcher import (
    endpoint_events_for_wave,
    haversine_m,
    load_airports,
    match_endpoint,
    nearest_airport,
)
from fr24.flight_fusion import (
    FUSION_VERSION,
    aircraft_identity,
    fuse_rows,
    fuse_wave,
    to_adapter_row,
)

__all__ = [
    "FUSION_VERSION",
    "aircraft_identity",
    "fuse_wave",
    "fuse_rows",
    "to_adapter_row",
    "nearest_airport",
    "match_endpoint",
    "endpoint_events_for_wave",
    "load_airports",
    "haversine_m",
    "reconstruct_flights",
    "build_track_points",
]


def reconstruct_flights(rows: List[dict]) -> List[dict]:
    """Reconstruct flight records from normalized per-screenshot observation rows.

    Groups rows by aircraft identity and fuses each group into a flight record.
    Alias of :func:`fr24.flight_fusion.fuse_rows`, surfaced as the canonical
    reconstruction entry point.
    """
    return fuse_rows(rows)


def build_track_points(points, max_points: int = 500) -> list:
    """Return an ordered, sampled list of track points for a reconstructed flight.

    Delegates to ``fr24.event_export._sample_points`` (lazy import) which caps
    the number of persisted points deterministically.
    """
    from fr24.event_export import _sample_points  # noqa: WPS433

    return _sample_points(list(points), max_points)
