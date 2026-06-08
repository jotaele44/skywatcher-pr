"""
iPhone FR24 portrait zone definitions for RLSM extraction.

Calibrated against 1170x2532 iPhone screenshots of the FR24 app (bottom-sheet
layout). Returns zone bboxes as fractional coordinates so the same definitions
work across rotation and image dimension variations.

Six canonical zones:

  status_bar      0–5%      iOS clock / signal / battery (sometimes flight clock)
  top_bar         5–12%     FR24 nav (search, settings)
  map_center      12–65%    main map viewport; flight track & labels live here
  label_layer     12–65%    same area, separate row per detected text label
  aircraft_card   65–95%    bottom sheet (callsign, route, altitude, speed, type, REG)
  bottom_actions  95–100%   action buttons (Route, More info, Follow)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


# (zone_name, x0%, y0%, x1%, y1%)
#
# Tier 1 trim: dropped top_bar (FR24 wordmark only) and bottom_actions ("Route Follow More info");
# merged label_layer into the same crop as map_center (one OCR call for the map area).
# Per-image cost dropped from ~5.8 s → ~2.5–3.0 s in sandbox; ~50% reduction.
PORTRAIT_ZONES: List[Tuple[str, float, float, float, float]] = [
    ("status_bar",     0.00, 0.000, 1.00, 0.050),
    ("label_layer",    0.00, 0.050, 1.00, 0.650),  # absorbed map_center; broader to catch top-of-map labels
    ("aircraft_card",  0.00, 0.650, 1.00, 0.950),
]

# Landscape (2532x1170) - aircraft card moves to a side strip rather than bottom sheet
LANDSCAPE_ZONES: List[Tuple[str, float, float, float, float]] = [
    ("status_bar",     0.00, 0.000, 1.00, 0.080),
    ("label_layer",    0.00, 0.080, 0.70, 0.950),
    ("aircraft_card",  0.70, 0.080, 1.00, 0.950),
]


@dataclass
class ZoneBox:
    name: str
    x: int
    y: int
    w: int
    h: int

    def crop_box(self) -> Tuple[int, int, int, int]:
        """PIL crop: (left, upper, right, lower)."""
        return (self.x, self.y, self.x + self.w, self.y + self.h)


def zones_for(width: int, height: int) -> List[ZoneBox]:
    """Pick portrait vs landscape based on aspect, return absolute pixel boxes."""
    portrait = height >= width
    base = PORTRAIT_ZONES if portrait else LANDSCAPE_ZONES
    out: List[ZoneBox] = []
    for name, x0, y0, x1, y1 in base:
        x = int(width * x0)
        y = int(height * y0)
        w = int(width * (x1 - x0))
        h = int(height * (y1 - y0))
        out.append(ZoneBox(name=name, x=x, y=y, w=w, h=h))
    return out


# OCR config per zone — different PSM modes work better for different content shapes.
ZONE_OCR_CONFIG = {
    "status_bar":     {"psm": 7,  "preprocess": "high_contrast"},       # single line
    "top_bar":        {"psm": 7,  "preprocess": "high_contrast"},
    "map_center":     {"psm": 11, "preprocess": "label_mask"},          # sparse text
    "label_layer":    {"psm": 11, "preprocess": "label_mask"},
    "aircraft_card":  {"psm": 6,  "preprocess": "high_contrast"},       # uniform block
    "bottom_actions": {"psm": 7,  "preprocess": "high_contrast"},
}
