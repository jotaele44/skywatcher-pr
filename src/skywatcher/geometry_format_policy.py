from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

State = Literal["PASS", "FAIL", "BLOCKED", "NONCANONICAL"]


@dataclass(frozen=True)
class TrackEncodingDecision:
    state: State
    reason: str


def assess_track_twkb(
    *,
    source_frozen: bool,
    crs: str | None,
    dimension: str | None,
    xy_precision: int | None,
    z_precision: int | None,
    roundtrip_ok: bool,
    type_conserved: bool,
    validity_conserved: bool,
    vertex_count_conserved: bool,
    application_tolerance: float | None,
    observed_max_error: float | None,
    canonical_track_retained: bool,
) -> TrackEncodingDecision:
    """Admit TWKB only as a backend/cache derivative for canonical flight tracks."""
    if not source_frozen:
        return TrackEncodingDecision("BLOCKED", "source track not frozen")
    if not crs:
        return TrackEncodingDecision("BLOCKED", "CRS missing")
    if not dimension:
        return TrackEncodingDecision("BLOCKED", "track dimension missing")
    if xy_precision is None:
        return TrackEncodingDecision("BLOCKED", "XY precision implicit/missing")
    if dimension in {"XYZ", "XYZM"} and z_precision is None:
        return TrackEncodingDecision("BLOCKED", "Z precision implicit/missing")
    if application_tolerance is None:
        return TrackEncodingDecision("BLOCKED", "application tolerance missing")
    if not canonical_track_retained:
        return TrackEncodingDecision("FAIL", "TWKB cannot be the sole track representation")
    if not all([roundtrip_ok, type_conserved, validity_conserved, vertex_count_conserved]):
        return TrackEncodingDecision("FAIL", "round-trip conservation invariant failed")
    if observed_max_error is None:
        return TrackEncodingDecision("BLOCKED", "observed round-trip error missing")
    if observed_max_error > application_tolerance:
        return TrackEncodingDecision("FAIL", "quantization error exceeds application tolerance")
    return TrackEncodingDecision("NONCANONICAL", "TWKB admitted for backend/cache use; GeoJSON remains map boundary")
