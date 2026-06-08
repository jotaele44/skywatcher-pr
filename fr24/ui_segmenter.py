"""
FR24 UI SEGMENTER
Detects the map area, bottom info panel, and UI overlay regions in
FlightRadar24 screenshot images using geometric heuristics (primary)
with optional edge-detection refinement when PIL/numpy are available.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Known FR24 web-app layout proportions (validated against PR-region screenshots)
MAP_TOP_FRAC    = 0.08   # top navigation bar height
MAP_BOTTOM_FRAC = 0.72   # map viewport ends here
PANEL_TOP_FRAC  = 0.72   # bottom flight-info panel starts
PANEL_BOTTOM_FRAC = 1.0

# Sidebar / UI chrome fractions (left toolbox, right info strip)
UI_LEFT_FRAC  = 0.04
UI_RIGHT_FRAC = 0.96


@dataclass
class BBox:
    x: int
    y: int
    w: int
    h: int

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    def crop_coords(self) -> Tuple[int, int, int, int]:
        """PIL-style (left, upper, right, lower)."""
        return (self.x, self.y, self.x + self.w, self.y + self.h)


@dataclass
class LabelRegion:
    bbox: BBox
    region_type: str   # "callsign" | "altitude" | "speed" | "route" | "unknown"
    confidence: float


@dataclass
class FR24Segments:
    map_bbox: BBox
    panel_bbox: BBox
    labels: List[LabelRegion] = field(default_factory=list)
    ui_mask: Optional[object] = None   # np.ndarray when available
    width: int = 0
    height: int = 0
    method: str = "geometric"
    confidence: float = 0.80


class FR24UISegmenter:
    """
    Segments FlightRadar24 screenshots into functional regions.

    mode options:
      "geometric"  — layout fractions only; no imaging dep; always works
      "edge"       — adds PIL-based edge refinement when available
    """

    def __init__(self, mode: str = "geometric"):
        if mode not in ("geometric", "edge"):
            raise ValueError("mode must be 'geometric' or 'edge'")
        self.mode = mode

    # ----------------------------------------------------------------- public

    def segment(self, image_path: str) -> FR24Segments:
        path = Path(image_path)
        w, h = self._get_dimensions(path)
        segs = self._geometric_segments(w, h)

        if self.mode == "edge" and w > 0 and h > 0:
            segs = self._refine_with_edges(path, segs)

        return segs

    def segment_from_size(self, width: int, height: int) -> FR24Segments:
        """Segment using only known dimensions (no file I/O)."""
        return self._geometric_segments(width, height)

    def segment_array(self, arr) -> FR24Segments:
        """
        Segment directly from a (H, W, 3) numpy/array-like.
        Applies edge refinement when mode='edge' without any file I/O.
        Useful for unit testing with synthetic images.
        """
        h, w = arr.shape[:2]
        segs = self._geometric_segments(w, h)
        if self.mode == "edge":
            segs = self._refine_array(arr, segs)
        segs.ui_mask = None
        return segs

    def get_map_region(self, image_path: str):
        """Return a PIL Image cropped to the map area, or None on failure."""
        try:
            from PIL import Image
            segs = self.segment(image_path)
            with Image.open(image_path) as img:
                return img.crop(segs.map_bbox.crop_coords())
        except Exception:
            return None

    def get_panel_region(self, image_path: str):
        """Return a PIL Image cropped to the bottom info panel."""
        try:
            from PIL import Image
            segs = self.segment(image_path)
            with Image.open(image_path) as img:
                return img.crop(segs.panel_bbox.crop_coords())
        except Exception:
            return None

    def detect_label_regions(self, width: int, height: int) -> List[LabelRegion]:
        """
        Estimate label positions within the bottom panel based on FR24 layout.
        Returns approximate regions for callsign, altitude, speed, route.
        """
        panel_y = int(height * PANEL_TOP_FRAC)
        panel_h = height - panel_y
        panel_w = width

        labels = []

        label_defs = [
            # (x_frac, y_frac_within_panel, w_frac, h_frac, type)
            (0.02, 0.05, 0.25, 0.30, "callsign"),
            (0.02, 0.40, 0.15, 0.25, "altitude"),
            (0.20, 0.40, 0.15, 0.25, "speed"),
            (0.40, 0.10, 0.55, 0.40, "route"),
        ]
        for xf, yf, wf, hf, ltype in label_defs:
            labels.append(LabelRegion(
                bbox=BBox(
                    x=int(xf * panel_w),
                    y=panel_y + int(yf * panel_h),
                    w=int(wf * panel_w),
                    h=int(hf * panel_h),
                ),
                region_type=ltype,
                confidence=0.75,
            ))
        return labels

    # ----------------------------------------------------------------- internal

    def _get_dimensions(self, path: Path) -> Tuple[int, int]:
        try:
            from PIL import Image
            with Image.open(path) as img:
                return img.size  # (width, height)
        except Exception:
            return 1024, 768  # FR24 default fallback

    def _geometric_segments(self, w: int, h: int) -> FR24Segments:
        map_bbox = BBox(
            x=int(w * UI_LEFT_FRAC),
            y=int(h * MAP_TOP_FRAC),
            w=int(w * (UI_RIGHT_FRAC - UI_LEFT_FRAC)),
            h=int(h * (MAP_BOTTOM_FRAC - MAP_TOP_FRAC)),
        )
        panel_bbox = BBox(
            x=0,
            y=int(h * PANEL_TOP_FRAC),
            w=w,
            h=int(h * (PANEL_BOTTOM_FRAC - PANEL_TOP_FRAC)),
        )
        labels = self.detect_label_regions(w, h)
        return FR24Segments(
            map_bbox=map_bbox,
            panel_bbox=panel_bbox,
            labels=labels,
            width=w,
            height=h,
            method="geometric",
            confidence=0.80,
        )

    def _refine_array(self, arr, segs: FR24Segments) -> FR24Segments:
        """Edge refinement operating directly on an array (no file I/O)."""
        try:
            import numpy as np
            grey = np.mean(arr[:, :, :3].astype(np.float32), axis=2)
            return self._apply_edge_refinement(grey, segs)
        except Exception:
            return segs

    def _refine_with_edges(self, path: Path, segs: FR24Segments) -> FR24Segments:
        """
        Attempt to refine map_bbox bottom boundary using horizontal edge
        density.  Falls back to geometric if imaging unavailable.
        """
        try:
            import numpy as np
            from PIL import Image
            with Image.open(path) as img:
                grey_arr = np.array(img.convert("L"), dtype=np.float32)
            return self._apply_edge_refinement(grey_arr, segs)
        except Exception:
            return segs

    def _apply_edge_refinement(self, grey: "np.ndarray",
                               segs: FR24Segments) -> FR24Segments:
        """Core edge-refinement logic operating on a 2-D float32 greyscale array."""
        try:
            import numpy as np
            h, w = grey.shape
            if h < 4:
                return segs

            gy = np.abs(grey[1:, :] - grey[:-1, :])
            row_energy = gy.mean(axis=1)

            lo = int(h * 0.60)
            hi = int(h * 0.85)
            search = row_energy[lo:hi]
            if search.size == 0:
                return segs

            boundary_y = lo + int(search.argmax())
            geometric_y = segs.map_bbox.y + segs.map_bbox.h
            if abs(boundary_y - geometric_y) > int(h * 0.12):
                return segs

            new_map_h = boundary_y - segs.map_bbox.y
            segs.map_bbox = BBox(segs.map_bbox.x, segs.map_bbox.y,
                                 segs.map_bbox.w, max(new_map_h, 10))
            segs.panel_bbox = BBox(0, boundary_y, w, max(h - boundary_y, 10))
            segs.method = "edge_detected"
            segs.confidence = 0.88
        except Exception:
            pass
        return segs

    # ----------------------------------------------------------------- batch

    def batch_segment(self, image_paths: List[str]) -> List[FR24Segments]:
        results = []
        for p in image_paths:
            try:
                results.append(self.segment(p))
            except Exception:
                results.append(self._geometric_segments(1024, 768))
        return results
