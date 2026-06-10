"""
ROUTE EXTRACTOR
Extracts FlightRadar24 colored route paths and aircraft icon positions
from screenshots via color thresholding and connected-component analysis.
Falls back gracefully when PIL/numpy are unavailable.
"""

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


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
MAX_LABEL_SKIP   = 4    # max gap when tracing a route (in pixels)


@dataclass
class RouteCandidate:
    color: str
    points: List[Tuple[int, int]] = field(default_factory=list)
    confidence: float = 0.0
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h
    pixel_length: float = 0.0
    pixel_count: int = 0

    def centroid(self) -> Tuple[float, float]:
        if not self.points:
            return (0.0, 0.0)
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (sum(xs) / len(xs), sum(ys) / len(ys))


class RouteExtractor:
    """
    Extracts FlightRadar24 colored route paths from screenshot images.

    Uses per-channel thresholding on the map region (as identified by
    FR24UISegmenter) to find pixels matching known FR24 route colors,
    then groups connected pixels into RouteCandidate objects.

    When PIL and numpy are not available, returns an empty list rather
    than raising so callers can degrade gracefully.
    """

    def __init__(self, segmenter=None):
        """
        segmenter: optional FR24UISegmenter instance.  When provided,
        extraction is restricted to the map region to avoid false
        positives from UI chrome.
        """
        self._segmenter = segmenter

    # ----------------------------------------------------------------- public

    def extract(self, image_path: str) -> List[RouteCandidate]:
        """Extract route candidates from a screenshot file."""
        try:
            import numpy as np
            from PIL import Image

            with Image.open(image_path) as img:
                arr = np.array(img.convert("RGB"), dtype=np.uint8)

            return self._extract_from_array(arr, image_path=image_path)
        except ImportError:
            return []
        except Exception:
            return []

    def extract_array(self, arr) -> List[RouteCandidate]:
        """
        Extract from a (H, W, 3) uint8 numpy array.
        Useful for unit testing with synthetic images.
        """
        try:
            return self._extract_from_array(arr)
        except Exception:
            return []

    def get_color_mask(self, arr, color: str):
        """
        Return a boolean mask for pixels matching a named FR24 color.
        Requires numpy; returns None if not available.
        """
        try:
            import numpy as np
            if color not in COLOR_RANGES:
                raise ValueError(f"Unknown color: {color}")
            rng = COLOR_RANGES[color]
            r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
            mask = (
                (r >= rng["r"][0]) & (r <= rng["r"][1]) &
                (g >= rng["g"][0]) & (g <= rng["g"][1]) &
                (b >= rng["b"][0]) & (b <= rng["b"][1])
            )
            return mask
        except ImportError:
            return None

    # ----------------------------------------------------------------- internal

    def _extract_from_array(self, arr, image_path: Optional[str] = None) -> List[RouteCandidate]:
        import numpy as np

        h, w = arr.shape[:2]

        # Restrict to map region when a segmenter is available
        x_off = y_off = 0
        map_arr = arr
        if self._segmenter is not None:
            try:
                if image_path:
                    segs = self._segmenter.segment(image_path)
                else:
                    segs = self._segmenter.segment_from_size(w, h)
                bb = segs.map_bbox
                x_off = bb.x
                y_off = bb.y
                map_arr = arr[bb.y:bb.y + bb.h, bb.x:bb.x + bb.w]
            except Exception:
                pass

        candidates = []
        for color_name in COLOR_RANGES:
            mask = self.get_color_mask(map_arr, color_name)
            if mask is None:
                continue
            components = self._connected_components(mask)
            for comp_pixels in components:
                if len(comp_pixels) < MIN_ROUTE_PIXELS:
                    continue
                # Translate back to full-image coordinates
                global_pts = [(px + x_off, py + y_off) for (px, py) in comp_pixels]
                bbox = _bbox_of_points(global_pts)
                plen = _polyline_length(global_pts)
                conf = min(1.0, len(global_pts) / 100.0)
                candidates.append(RouteCandidate(
                    color=color_name,
                    points=global_pts,
                    confidence=conf,
                    bbox=bbox,
                    pixel_length=plen,
                    pixel_count=len(global_pts),
                ))

        # Sort by pixel count descending (most prominent routes first)
        candidates.sort(key=lambda c: c.pixel_count, reverse=True)
        return candidates

    def _connected_components(self, mask) -> List[List[Tuple[int, int]]]:
        """
        4-connected component labeling via BFS on a boolean mask.
        Returns list of pixel-lists, one per component.
        """
        import numpy as np

        visited = np.zeros(mask.shape, dtype=bool)
        h, w = mask.shape
        components = []

        ys, xs = np.where(mask)
        seed_pts = list(zip(xs.tolist(), ys.tolist()))

        for sx, sy in seed_pts:
            if visited[sy, sx]:
                continue
            # BFS
            component: List[Tuple[int, int]] = []
            queue = [(sx, sy)]
            visited[sy, sx] = True
            while queue:
                cx, cy = queue.pop()
                component.append((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx] and mask[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((nx, ny))
            components.append(component)

        return components


# ------------------------------------------------------------------ helpers

def _bbox_of_points(pts: List[Tuple[int, int]]) -> Tuple[int, int, int, int]:
    if not pts:
        return (0, 0, 0, 0)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, y0 = min(xs), min(ys)
    return (x0, y0, max(xs) - x0, max(ys) - y0)


def _polyline_length(pts: List[Tuple[int, int]]) -> float:
    if len(pts) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(pts)):
        dx = pts[i][0] - pts[i - 1][0]
        dy = pts[i][1] - pts[i - 1][1]
        total += math.sqrt(dx * dx + dy * dy)
    return total
