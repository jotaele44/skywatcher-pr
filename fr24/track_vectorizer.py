"""Track-polyline CV (strategy #4) — vectorize the on-screen FR24 trail.

The route line drawn in every screenshot was previously discarded:
fr24/rlsm_flight_track.py classifies from speed/heading OCR fields only and
leaves has_loop/has_orbit/has_gap, track_length_px, and bbox_* at 0/NULL
("we couldn't look"). This module looks: it reuses fr24/route_extractor.py's
color-mask + connected-component pass and derives shape features from the
pixel geometry — unlocking the loiter/orbit behaviors the ILAP scoring
weights highest.

Classification (per largest track-colored component):
  - closed ring (>=90% angular coverage around the centroid with a hollow
    center) -> 'orbit' when the ring is near-circular, else 'loop'
  - dominant principal axis -> 'linear'
  - anything else -> 'curve'
  - >=2 substantial components of the same color family -> has_gap=1

Honest limits: pixel space only — follows_coast / near_airport stay 0 (they
need the geo layer); track_length_px is an estimate (principal-axis extent,
or ring circumference for closed shapes); an aircraft icon overlapping the
trail can distort small components, hence MIN_TRACK_PIXELS. CV confidence is
a flat 0.6 — above the 0.3 speed/heading heuristic, below reviewed truth.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from fr24.route_extractor import RouteCandidate, RouteExtractor

CV_CONFIDENCE = 0.6

# FR24 draws trails in the warm family; blue/green/white mask UI chrome,
# water, and terrain far more often than trails.
TRACK_COLORS = ("orange", "yellow", "red")

MIN_TRACK_PIXELS = 30          # below this a component is icon/noise, not trail
ANGULAR_BINS = 36              # 10-degree bins for ring coverage
CLOSED_COVERAGE = 0.9          # fraction of bins occupied to call a shape closed
HOLLOW_MIN_RADIUS_RATIO = 0.25 # p5(r)/max(r) floor: rings are hollow, blobs aren't
ORBIT_MAX_RADIAL_RELSTD = 0.25 # radial std/mean below this: circular enough for orbit
LINEAR_MAX_AXIS_RATIO = 0.05   # secondary/principal variance ratio for 'linear'


@dataclass
class TrackFeatures:
    path_shape: str            # 'linear'|'curve'|'loop'|'orbit'
    has_loop: int
    has_orbit: int
    has_gap: int
    track_length_px: float
    bbox: Tuple[int, int, int, int]
    confidence: float
    component_count: int


def _component_geometry(points: List[Tuple[int, int]]) -> dict:
    """Shape statistics for one connected component's pixel set."""
    import numpy as np

    xs = np.array([p[0] for p in points], dtype=float)
    ys = np.array([p[1] for p in points], dtype=float)
    cx, cy = xs.mean(), ys.mean()
    dx, dy = xs - cx, ys - cy

    # Principal axes via the 2x2 covariance eigenvalues.
    cov = np.cov(np.stack([dx, dy]))
    eigvals = np.sort(np.linalg.eigvalsh(cov))[::-1]
    principal, secondary = float(eigvals[0]), float(eigvals[1])
    axis_ratio = secondary / principal if principal > 0 else 1.0

    # Extent along the principal axis (straight-stroke length estimate).
    eigvecs = np.linalg.eigh(cov)[1]
    main_vec = eigvecs[:, -1]
    projection = dx * main_vec[0] + dy * main_vec[1]
    principal_extent = float(projection.max() - projection.min())

    # Ring statistics around the centroid.
    radii = np.hypot(dx, dy)
    angles = np.arctan2(dy, dx)
    bins = np.floor((angles + math.pi) / (2 * math.pi) * ANGULAR_BINS).astype(int)
    bins = np.clip(bins, 0, ANGULAR_BINS - 1)
    coverage = len(np.unique(bins)) / ANGULAR_BINS
    mean_r = float(radii.mean())
    rel_std = float(radii.std() / mean_r) if mean_r > 0 else 1.0
    hollow = (float(np.percentile(radii, 5)) / float(radii.max())
              if radii.max() > 0 else 0.0)

    return {
        "axis_ratio": axis_ratio,
        "principal_extent": principal_extent,
        "coverage": coverage,
        "mean_r": mean_r,
        "rel_std": rel_std,
        "hollow": hollow,
    }


def _classify_component(geometry: dict) -> str:
    closed = (geometry["coverage"] >= CLOSED_COVERAGE
              and geometry["hollow"] >= HOLLOW_MIN_RADIUS_RATIO)
    if closed:
        return "orbit" if geometry["rel_std"] <= ORBIT_MAX_RADIAL_RELSTD else "loop"
    if geometry["axis_ratio"] <= LINEAR_MAX_AXIS_RATIO:
        return "linear"
    return "curve"


def _component_length(shape: str, geometry: dict) -> float:
    if shape in ("orbit", "loop"):
        return 2.0 * math.pi * geometry["mean_r"]
    return geometry["principal_extent"]


def vectorize_candidates(candidates: List[RouteCandidate]) -> Optional[TrackFeatures]:
    """Derive TrackFeatures from extracted route components, or None when no
    track-colored component is substantial enough to trust."""
    tracks = [
        c for c in candidates
        if c.color in TRACK_COLORS and c.pixel_count >= MIN_TRACK_PIXELS
    ]
    if not tracks:
        return None

    tracks.sort(key=lambda c: c.pixel_count, reverse=True)
    main = tracks[0]
    geometry = _component_geometry(main.points)
    shape = _classify_component(geometry)

    total_length = 0.0
    x0 = y0 = None
    x1 = y1 = None
    for component in tracks:
        comp_geometry = geometry if component is main else _component_geometry(component.points)
        comp_shape = shape if component is main else _classify_component(comp_geometry)
        total_length += _component_length(comp_shape, comp_geometry)
        bx, by, bw, bh = component.bbox
        x0 = bx if x0 is None else min(x0, bx)
        y0 = by if y0 is None else min(y0, by)
        x1 = bx + bw if x1 is None else max(x1, bx + bw)
        y1 = by + bh if y1 is None else max(y1, by + bh)

    return TrackFeatures(
        path_shape=shape,
        has_loop=1 if shape in ("loop", "orbit") else 0,
        has_orbit=1 if shape == "orbit" else 0,
        has_gap=1 if len(tracks) >= 2 else 0,
        track_length_px=round(total_length, 1),
        bbox=(int(x0), int(y0), int(x1 - x0), int(y1 - y0)),
        confidence=CV_CONFIDENCE,
        component_count=len(tracks),
    )


def vectorize_image(image_path: str,
                    extractor: Optional[RouteExtractor] = None) -> Optional[TrackFeatures]:
    """Extract + vectorize one screenshot file. None on any failure — callers
    fall back to the speed/heading heuristic."""
    if extractor is None:
        try:
            from fr24.ui_segmenter import FR24UISegmenter
            extractor = RouteExtractor(FR24UISegmenter(mode="geometric"))
        except Exception:
            extractor = RouteExtractor()
    candidates = extractor.extract(image_path)
    if not candidates:
        return None
    try:
        return vectorize_candidates(candidates)
    except Exception:
        return None
