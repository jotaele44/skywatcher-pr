"""
iPhone FR24 zone definitions for RLSM extraction — portrait and landscape.

Calibrated against 1170x2532 iPhone screenshots of the FR24 app (bottom-sheet
layout). Returns zone bboxes as fractional coordinates so the same definitions
work across rotation and image dimension variations.

Both orientations carry the **same three zone names** (``status_bar``,
``label_layer``, ``aircraft_card``), which is what lets everything downstream
stay orientation-agnostic: the extractor's per-zone confidence weights, the
word-box offsets and the review queue all key on the name, not on geometry.
Only the fractions differ — in landscape the aircraft card is a right-hand strip
rather than a bottom sheet, so ``label_layer`` gives up width instead of height.
Use ``orientation_for()`` rather than re-deriving the aspect rule.

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

# (zone_name, x0%, y0%, x1%, y1%)
#
# Tier 1 trim: dropped top_bar (FR24 wordmark only) and bottom_actions ("Route Follow More info");
# merged label_layer into the same crop as map_center (one OCR call for the map area).
# Per-image cost dropped from ~5.8 s → ~2.5–3.0 s in sandbox; ~50% reduction.
PORTRAIT_ZONES: list[tuple[str, float, float, float, float]] = [
    ("status_bar",     0.00, 0.000, 1.00, 0.050),
    ("label_layer",    0.00, 0.050, 1.00, 0.650),  # absorbed map_center; broader to catch top-of-map labels
    ("aircraft_card",  0.00, 0.650, 1.00, 0.950),
]

# Landscape (2532x1170) - aircraft card moves to a side strip rather than bottom sheet
LANDSCAPE_ZONES: list[tuple[str, float, float, float, float]] = [
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

    def crop_box(self) -> tuple[int, int, int, int]:
        """PIL crop: (left, upper, right, lower)."""
        return (self.x, self.y, self.x + self.w, self.y + self.h)


PORTRAIT = "portrait"
LANDSCAPE = "landscape"


def orientation_for(width: int, height: int) -> str:
    """
    ``"portrait"`` or ``"landscape"`` from frame dimensions.

    The single source of truth for the aspect rule. Every consumer that needs to
    branch on orientation — zone selection, the icon glyph search, the run
    report — calls this instead of re-deriving ``height >= width`` locally, so
    the two layouts can never disagree about which one a frame is.

    Square frames count as portrait, matching the FR24 bottom-sheet layout.
    """
    return PORTRAIT if height >= width else LANDSCAPE


# The same rule expressed for SQL, so reports can group by orientation without a
# second definition drifting from the one above. Format with the table alias:
#     ORIENTATION_SQL.format(t="s")
# tests/test_rlsm_label_extraction.py asserts the two agree on real dimensions.
ORIENTATION_SQL = (
    "CASE WHEN {t}.height >= {t}.width THEN 'portrait' ELSE 'landscape' END"
)


def zones_for(width: int, height: int) -> list[ZoneBox]:
    """Pick portrait vs landscape based on aspect, return absolute pixel boxes."""
    base = (PORTRAIT_ZONES if orientation_for(width, height) == PORTRAIT
            else LANDSCAPE_ZONES)
    out: list[ZoneBox] = []
    for name, x0, y0, x1, y1 in base:
        x = int(width * x0)
        y = int(height * y0)
        w = int(width * (x1 - x0))
        h = int(height * (y1 - y0))
        out.append(ZoneBox(name=name, x=x, y=y, w=w, h=h))
    return out


# OCR config per zone — different PSM modes work better for different content shapes.
# ``preprocess`` is applied by fr24.rlsm_preprocess.preprocess(); ``scale`` is
# the upscale used before binarizing, and every consumer of the resulting word
# boxes must divide it back out (fr24.rlsm_wordboxes takes a ``scale`` arg).
# Until this was wired up, both runners read the key and ignored it.
#
# Measured with scripts/rlsm_ocr_bench.py over 22 screenshots stride-sampled
# across all month buckets — mean word confidence / words per frame / distinct
# gazetteer hits per frame / seconds:
#
#   label_layer     raw            39.2 /  53.1 / 0.41 / 2.64
#                   label_mask@2x  40.4 / 135.7 / 0.86 / 3.04   <- kept
#                   high_contrast  39.9 / 142.5 / 0.86 / 3.33
#                   label_mask@3x  39.6 / 151.8 / 0.85 / 4.39   (slower, no gain)
#   aircraft_card   raw            55.4 /  52.6 / 0.30 / 1.45
#                   high_contrast  60.8 /  58.3 / 0.77 / 1.36   <- kept, also faster
#                   label_mask@2x  61.4 /  56.7 / 0.77 / 1.37
#
# What the sample supports: preprocessing roughly DOUBLES gazetteer hits per
# frame on both zones. On the label layer that comes from recall — 2.6x the
# words recovered — not from higher per-word confidence, which barely moves;
# on the aircraft card confidence rises 5.4 points. What it does NOT support:
# a preference between label_mask@2x and high_contrast (they are inside the
# noise of each other), or any 3x upscale. Each zone therefore keeps the mode
# the schema originally declared. Re-run the bench before changing either.
# Hit counts were taken against fr24/rlsm_gazetteer.py; confidence and word
# counts are engine-level and vocabulary-independent.
ZONE_OCR_CONFIG = {
    "status_bar":     {"psm": 7,  "preprocess": "high_contrast", "scale": 2.0},
    "top_bar":        {"psm": 7,  "preprocess": "high_contrast", "scale": 2.0},
    "map_center":     {"psm": 11, "preprocess": "label_mask",    "scale": 2.0},
    "label_layer":    {"psm": 11, "preprocess": "label_mask",    "scale": 2.0},
    "aircraft_card":  {"psm": 6,  "preprocess": "high_contrast", "scale": 2.0},
    "bottom_actions": {"psm": 7,  "preprocess": "high_contrast", "scale": 2.0},
}
