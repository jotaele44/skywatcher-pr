"""Shared FR24 screenshot color-detection constants.

Used by both SATIM's calibration layers (fr24/calibration/l2_route_calibration.py)
and FPIM's route extraction (fr24/route_extractor.py) — a pixel-color threshold
table is a shared visual-detection primitive, not domain-specific logic, so it
lives in Core rather than being duplicated or cross-imported between buckets.
See docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md.
"""

from __future__ import annotations

from typing import Dict, Tuple

# FR24 route color definitions in RGB space
COLOR_RANGES: Dict[str, Dict[str, Tuple[int, int]]] = {
    "orange": {"r": (190, 255), "g": (80,  180), "b": (0,   80)},
    "yellow": {"r": (200, 255), "g": (190, 255), "b": (0,   80)},
    "green":  {"r": (0,   120), "g": (150, 255), "b": (0,  120)},
    "blue":   {"r": (0,   120), "g": (100, 200), "b": (140, 255)},
    "red":    {"r": (190, 255), "g": (0,    80), "b": (0,   80)},
    "white":  {"r": (220, 255), "g": (220, 255), "b": (220, 255)},
}

MIN_ROUTE_PIXELS = 8    # minimum connected pixels to count as a route segment
