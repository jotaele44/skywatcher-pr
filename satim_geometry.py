"""Parallax / geometry-coherence and rectilinear mosaic-seam detection.

An empirical add-on to the SATIM calibration engine (``satim_calibration.py``).
Main's engine scores a marked label and assigns a conservative promotion band; this
module supplies a *geometry gate* that can only ever lower that band, never raise
it.

Two signals, both derived from a frame's recorded kinematics (altitude_ft,
ground_speed_mph) plus an upstream edge/feature descriptor — no image pixels are
processed here:

* **Parallax coherence** — a real ground feature, viewed from a moving aircraft,
  shifts between frames by roughly the platform's horizontal ground-track
  displacement; a screen-locked artifact (UI overlay, FR24 tile seam, LOD
  boundary) does not. An observed shift inconsistent with the recorded motion is
  incoherent.
* **Rectilinear mosaic seam** — a basemap tile boundary where adjacent orthoimagery
  is stitched from different captures: a hard, axis-aligned tonal edge that stays
  screen-locked. It corresponds to nothing on the ground and must be suppressed.
  Per the taxonomy decision it is *not* a new false-positive class; it stays within
  the engine's existing ``FR24_3D_RENDER`` tile/LOD family and is routed to
  suppression through :func:`cap_decision_for_geometry`.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# "src" is only on sys.path automatically under pytest (pyproject.toml's
# pythonpath setting); bootstrap it here so this module resolves regardless
# of the calling entry point (see docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md).
_SRC_DIR = Path(__file__).resolve().parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# Reuse the repo's haversine so callers can convert lat/lon marks to a metric
# shift without a second geodesy implementation.
from skywatcher.core.geo_utils import haversine_m  # noqa: F401

MPH_TO_M_S = 0.44704
FT_TO_M = 0.3048

# A feature shift may legitimately differ from the platform displacement by this
# fraction (registration noise, oblique foreshortening) and still be coherent.
DEFAULT_PARALLAX_TOLERANCE = 0.5

# Promotion bands from satim_calibration.promotion_decision, ordered low -> high,
# so the geometry gate can cap (never raise) a decision.
_DECISION_RANK = {
    "suppressed": 0,
    "review": 1,
    "cross_source_required": 2,
    "candidate": 3,
}


# ---------------------------------------------------------------------------
# Parallax coherence
# ---------------------------------------------------------------------------
def ground_track_distance_m(ground_speed_mph: float, dt_s: float) -> float:
    """Horizontal distance the platform travels over ``dt_s`` seconds."""
    return max(0.0, float(ground_speed_mph)) * MPH_TO_M_S * max(0.0, float(dt_s))


def expected_parallax_m(ground_speed_mph: float, dt_s: float) -> float:
    """Apparent ground-feature shift expected between two frames.

    To first order at near-nadir view, a ground feature's image displacement
    equals the platform's horizontal ground-track displacement.
    """
    return ground_track_distance_m(ground_speed_mph, dt_s)


def parallax_coherence(
    observed_shift_m: float,
    ground_speed_mph: float,
    dt_s: float,
    *,
    tolerance: float = DEFAULT_PARALLAX_TOLERANCE,
) -> bool:
    """Whether an observed inter-frame shift matches the expected parallax.

    When the platform barely moved (``expected`` ~ 0) the test is uninformative
    and returns ``True``. Otherwise the observed shift must fall within
    ``tolerance`` of the expected displacement; a near-zero observed shift under
    real motion reads as a screen-locked artifact and fails.
    """
    expected = expected_parallax_m(ground_speed_mph, dt_s)
    if expected <= 0.0:
        return True
    ratio = max(0.0, float(observed_shift_m)) / expected
    return (1.0 - tolerance) <= ratio <= (1.0 + tolerance)


def within_envelope(value: float, envelope: Iterable[float], *, margin: float) -> bool:
    """Whether ``value`` lies within ``margin`` of an observed-value envelope."""
    bounds = [float(v) for v in envelope]
    if not bounds:
        return True
    return (min(bounds) - margin) <= float(value) <= (max(bounds) + margin)


def is_geometry_coherent(
    observed_shift_m: float,
    *,
    ground_speed_mph: float,
    dt_s: float,
    altitude_ft: float | None = None,
    altitude_envelope: Iterable[float] | None = None,
    altitude_margin_ft: float = 200.0,
    tolerance: float = DEFAULT_PARALLAX_TOLERANCE,
) -> bool:
    """Combined coherence gate: parallax consistency and altitude plausibility."""
    if not parallax_coherence(observed_shift_m, ground_speed_mph, dt_s, tolerance=tolerance):
        return False
    if altitude_ft is not None and altitude_envelope is not None:
        if not within_envelope(altitude_ft, altitude_envelope, margin=altitude_margin_ft):
            return False
    return True


# ---------------------------------------------------------------------------
# Rectilinear mosaic-seam detection
# ---------------------------------------------------------------------------
DEFAULT_AXIS_TOLERANCE_DEG = 12.0
DEFAULT_STRAIGHTNESS_MIN = 0.85
DEFAULT_TONAL_DELTA_MIN = 0.15


@dataclass(frozen=True)
class EdgeFeature:
    """A marked edge described by geometry an upstream extractor would supply.

    ``orientation_deg`` is measured from horizontal (0 = horizontal, 90 = vertical);
    ``straightness`` and ``tonal_delta`` are ``[0, 1]`` scores; ``observed_shift_m``
    is the edge's inter-frame screen displacement under the recorded kinematics.
    """

    orientation_deg: float
    straightness: float
    tonal_delta: float
    observed_shift_m: float
    ground_speed_mph: float
    dt_s: float


def is_axis_aligned(orientation_deg: float, tol_deg: float = DEFAULT_AXIS_TOLERANCE_DEG) -> bool:
    """Whether an orientation is within ``tol_deg`` of horizontal or vertical."""
    angle = abs(float(orientation_deg)) % 180.0
    near_horizontal = angle <= tol_deg or angle >= 180.0 - tol_deg
    near_vertical = abs(angle - 90.0) <= tol_deg
    return near_horizontal or near_vertical


def is_screen_locked(edge: EdgeFeature, *, tolerance: float = DEFAULT_PARALLAX_TOLERANCE) -> bool:
    """Whether the edge stays put while the platform moves (no parallax shift)."""
    if expected_parallax_m(edge.ground_speed_mph, edge.dt_s) <= 0.0:
        return False
    return not parallax_coherence(
        edge.observed_shift_m, edge.ground_speed_mph, edge.dt_s, tolerance=tolerance
    )


def is_rectilinear_seam(
    edge: EdgeFeature,
    *,
    straightness_min: float = DEFAULT_STRAIGHTNESS_MIN,
    tonal_delta_min: float = DEFAULT_TONAL_DELTA_MIN,
    axis_tol_deg: float = DEFAULT_AXIS_TOLERANCE_DEG,
    parallax_tolerance: float = DEFAULT_PARALLAX_TOLERANCE,
) -> bool:
    """Whether an edge matches the mosaic-seam fingerprint (straight + axis-aligned
    + tonal discontinuity + screen-locked)."""
    return (
        edge.straightness >= straightness_min
        and edge.tonal_delta >= tonal_delta_min
        and is_axis_aligned(edge.orientation_deg, axis_tol_deg)
        and is_screen_locked(edge, tolerance=parallax_tolerance)
    )


def seam_confidence(edge: EdgeFeature, *, parallax_tolerance: float = DEFAULT_PARALLAX_TOLERANCE) -> float:
    """Graded ``[0, 1]`` strength that ``edge`` is a mosaic seam, for ranking."""
    if not is_axis_aligned(edge.orientation_deg):
        return 0.0
    if not is_screen_locked(edge, tolerance=parallax_tolerance):
        return 0.0
    return max(0.0, min(1.0, edge.straightness)) * max(0.0, min(1.0, edge.tonal_delta))


def detect_seam_box(
    edges: Iterable[EdgeFeature],
    *,
    axis_tol_deg: float = DEFAULT_AXIS_TOLERANCE_DEG,
    **seam_kwargs: Any,
) -> bool:
    """Whether the edges corroborate a seam *box* (a corner), not a lone line."""
    seams = [e for e in edges if is_rectilinear_seam(e, axis_tol_deg=axis_tol_deg, **seam_kwargs)]
    has_horizontal = any(
        (abs(e.orientation_deg) % 180.0) <= axis_tol_deg
        or (abs(e.orientation_deg) % 180.0) >= 180.0 - axis_tol_deg
        for e in seams
    )
    has_vertical = any(abs((abs(e.orientation_deg) % 180.0) - 90.0) <= axis_tol_deg for e in seams)
    return has_horizontal and has_vertical


# ---------------------------------------------------------------------------
# Engine integration
# ---------------------------------------------------------------------------
def cap_decision_for_geometry(decision: str, geometry_coherent: bool | None) -> str:
    """Lower a promotion ``decision`` to ``review`` when geometry is incoherent.

    ``decision`` is the band from :func:`satim_calibration.promotion_decision`. A
    ``geometry_coherent=False`` verdict (e.g. a detected mosaic seam) caps the band
    at ``review`` so a screen-locked artifact can never auto-promote; a coherent or
    unknown verdict leaves the decision untouched.
    """
    if geometry_coherent is False and _DECISION_RANK.get(decision, 0) > _DECISION_RANK["review"]:
        return "review"
    return decision
