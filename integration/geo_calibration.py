"""
GEO CALIBRATION
Converts pixel coordinates in FlightRadar24 screenshots to geographic coordinates
with explicit uncertainty metadata. Four modes:
  fixed_pr_bounds      — uses hardcoded Puerto Rico map bounds (baseline)
  airport_anchor       — bilinear interpolation from known airport pixel positions
  manual_anchor_csv    — user-supplied anchor CSV for highest accuracy
  per_screenshot_affine— 4-parameter affine fit from >=2 per-image anchors
                         (RLSM geo_anchors / vocab-matched labeled pins);
                         confidence and error are residual-driven, and the
                         instance falls back to fixed_pr_bounds when the fit
                         is unavailable or degenerate
"""

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import List, Optional, Sequence, Tuple


PR_BOUNDS = {"north": 18.65, "south": 17.92, "east": -65.20, "west": -67.30}

MAP_TOP_FRACTION    = 0.15
MAP_BOTTOM_FRACTION = 0.75

DEFAULT_ANCHORS_CSV = Path(__file__).resolve().parent.parent / "configs" / "georef_anchors.csv"

DEG_TO_M = 111_000.0
# A screenshot-pixel fit can't honestly claim better than ~50 m even when the
# anchor residual is zero (2 exact anchors fit exactly).
MIN_AFFINE_ERROR_M = 50.0


def fit_affine(pixel_xy: Sequence[Tuple[float, float]],
               geo_latlon: Sequence[Tuple[float, float]]):
    """4-parameter affine fit: returns (lon0, dlon_dx, lat0, dlat_dy) or None.

    Two independent 1-D ordinary-least-squares fits (lon on pixel_x, lat on
    pixel_y — FR24 map tiles are axis-aligned). Requires >=2 anchors with
    pixel spread on both axes; returns None on a degenerate scale.
    """
    n = len(pixel_xy)
    if n < 2 or len(geo_latlon) != n:
        return None
    px   = [float(p[0]) for p in pixel_xy]
    py   = [float(p[1]) for p in pixel_xy]
    lats = [float(g[0]) for g in geo_latlon]
    lons = [float(g[1]) for g in geo_latlon]

    def _ols(xs, ys):
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        sxx = sum((x - mean_x) ** 2 for x in xs)
        if sxx <= 0.0:
            return None
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / sxx
        return mean_y - slope * mean_x, slope

    lon_fit = _ols(px, lons)
    lat_fit = _ols(py, lats)
    if lon_fit is None or lat_fit is None:
        return None
    a, b = lon_fit
    c, d = lat_fit
    if abs(b) < 1e-7 or abs(d) < 1e-7:
        return None
    return (a, b, c, d)


def apply_affine(affine, px: float, py: float) -> Tuple[float, float]:
    """Apply a fit_affine() transform to a pixel; returns (lat, lon)."""
    a, b, c, d = affine
    return c + d * py, a + b * px


def invert_fixed_pr_bounds(lat: float, lon: float,
                           img_w: int, img_h: int) -> Tuple[float, float]:
    """Recover the pixel that the fixed_pr_bounds mapping sent to (lat, lon).

    Used by the RLSM calibration bridge to refit legacy fixed-bounds stamps
    with a per-screenshot affine: invert the stamp back to its pixel, then
    re-project that pixel through the better transform.
    """
    rel_y = (PR_BOUNDS["north"] - lat) / (PR_BOUNDS["north"] - PR_BOUNDS["south"])
    rel_x = (lon - PR_BOUNDS["west"]) / (PR_BOUNDS["east"] - PR_BOUNDS["west"])
    map_top_px = img_h * MAP_TOP_FRACTION
    map_h = img_h * (MAP_BOTTOM_FRACTION - MAP_TOP_FRACTION)
    return rel_x * img_w, map_top_px + rel_y * map_h


def affine_median_residual_deg(affine,
                               pixel_xy: Sequence[Tuple[float, float]],
                               geo_latlon: Sequence[Tuple[float, float]]) -> float:
    """Median euclidean residual (degrees) of the fit over its own anchors."""
    residuals = []
    for (px, py), (lat, lon) in zip(pixel_xy, geo_latlon):
        est_lat, est_lon = apply_affine(affine, px, py)
        residuals.append(math.hypot(est_lat - lat, est_lon - lon))
    return float(median(residuals))


@dataclass
class CoordResult:
    lat: float
    lon: float
    coordinate_method: str
    coordinate_confidence: float
    estimated_error_m: float

    def in_pr_bbox(self) -> bool:
        return (PR_BOUNDS["south"] <= self.lat <= PR_BOUNDS["north"] and
                PR_BOUNDS["west"]  <= self.lon <= PR_BOUNDS["east"])

    def to_dict(self) -> dict:
        return {
            "lat": self.lat,
            "lon": self.lon,
            "coordinate_method": self.coordinate_method,
            "coordinate_confidence": self.coordinate_confidence,
            "estimated_error_m": self.estimated_error_m,
        }


@dataclass
class _Anchor:
    anchor_id: str
    name: str
    pixel_x_fraction: float
    pixel_y_fraction: float
    lat: float
    lon: float


class GeoCalibration:
    """
    Pixel → geographic coordinate conversion with per-result confidence metadata.

    mode options:
      "fixed_pr_bounds"  — deterministic; confidence 0.65; ~1500 m error
      "airport_anchor"   — bilinear from bundled airport anchors; 0.82; ~500 m
      "manual_anchor_csv"— user CSV; 0.90; ~200 m
      "per_screenshot_affine" — affine fit from per-image anchors
                          [(pixel_x, pixel_y, lat, lon), ...]; confidence and
                          error come from the fit residual (<=150 m -> 0.90,
                          <=500 m -> 0.82, else 0.70); falls back to
                          fixed_pr_bounds when <2 usable anchors or the fit
                          is degenerate
    """

    MODE_META = {
        "fixed_pr_bounds":   {"confidence": 0.65, "error_m": 1500.0},
        "airport_anchor":    {"confidence": 0.82, "error_m":  500.0},
        "manual_anchor_csv": {"confidence": 0.90, "error_m":  200.0},
        # Residual-driven per instance; these are the worst-case defaults.
        "per_screenshot_affine": {"confidence": 0.70, "error_m": 1500.0},
    }

    def __init__(self, mode: str = "fixed_pr_bounds",
                 anchors_csv: Optional[str] = None,
                 anchors: Optional[Sequence[Tuple[float, float, float, float]]] = None):
        if mode not in self.MODE_META:
            raise ValueError(f"mode must be one of {list(self.MODE_META)}")
        self.mode = mode
        self._anchors: List[_Anchor] = []
        self._affine = None
        self._affine_residual_deg: Optional[float] = None
        self._affine_confidence = self.MODE_META["per_screenshot_affine"]["confidence"]
        self._affine_error_m = self.MODE_META["per_screenshot_affine"]["error_m"]
        if mode in ("airport_anchor", "manual_anchor_csv"):
            csv_path = anchors_csv or (None if mode == "manual_anchor_csv" else str(DEFAULT_ANCHORS_CSV))
            if csv_path is None and mode == "manual_anchor_csv":
                raise ValueError("manual_anchor_csv mode requires anchors_csv path")
            if csv_path is None:
                csv_path = str(DEFAULT_ANCHORS_CSV)
            self._anchors = self._load_anchors(csv_path)
        elif mode == "per_screenshot_affine":
            self._fit_from_anchors(anchors or [])

    @property
    def affine(self):
        """The fitted (lon0, dlon_dx, lat0, dlat_dy) transform, or None."""
        return self._affine

    @property
    def affine_residual_deg(self) -> Optional[float]:
        """Median anchor residual (degrees) of the fitted transform, or None."""
        return self._affine_residual_deg

    def _fit_from_anchors(self, anchors: Sequence[Tuple[float, float, float, float]]) -> None:
        seen = set()
        pixel_xy: List[Tuple[float, float]] = []
        geo_latlon: List[Tuple[float, float]] = []
        for px, py, lat, lon in anchors:
            key = (round(float(px), 1), round(float(py), 1))
            if key in seen:
                continue
            seen.add(key)
            pixel_xy.append((float(px), float(py)))
            geo_latlon.append((float(lat), float(lon)))
        if len(pixel_xy) < 2:
            return
        affine = fit_affine(pixel_xy, geo_latlon)
        if affine is None:
            return
        residual_deg = affine_median_residual_deg(affine, pixel_xy, geo_latlon)
        error_m = max(residual_deg * DEG_TO_M, MIN_AFFINE_ERROR_M)
        if error_m <= 150.0:
            confidence = 0.90
        elif error_m <= 500.0:
            confidence = 0.82
        else:
            confidence = 0.70
        self._affine = affine
        self._affine_residual_deg = residual_deg
        self._affine_confidence = confidence
        self._affine_error_m = round(error_m, 1)

    def pixel_to_coord(self, px: float, py: float,
                       img_w: int, img_h: int) -> CoordResult:
        if self.mode == "per_screenshot_affine":
            if self._affine is not None:
                lat, lon = apply_affine(self._affine, px, py)
                return CoordResult(
                    lat=round(lat, 5), lon=round(lon, 5),
                    coordinate_method="per_screenshot_affine",
                    coordinate_confidence=self._affine_confidence,
                    estimated_error_m=self._affine_error_m,
                )
            # Honest fallback: report the method actually used, not the one asked for.
            lat, lon = self._fixed_pr_bounds(px, py, img_w, img_h)
            meta = self.MODE_META["fixed_pr_bounds"]
            return CoordResult(
                lat=round(lat, 5), lon=round(lon, 5),
                coordinate_method="fixed_pr_bounds",
                coordinate_confidence=meta["confidence"],
                estimated_error_m=meta["error_m"],
            )
        if self.mode == "fixed_pr_bounds":
            lat, lon = self._fixed_pr_bounds(px, py, img_w, img_h)
        elif self.mode == "airport_anchor":
            lat, lon = self._anchor_interpolate(px, py, img_w, img_h)
        else:
            lat, lon = self._anchor_interpolate(px, py, img_w, img_h)

        meta = self.MODE_META[self.mode]
        lat = round(lat, 5)
        lon = round(lon, 5)
        return CoordResult(
            lat=lat, lon=lon,
            coordinate_method=self.mode,
            coordinate_confidence=meta["confidence"],
            estimated_error_m=meta["error_m"],
        )

    def generate_quality_report(self, rows: List[dict], output_path: str) -> int:
        """
        Write georef_quality_report.csv from a list of dicts that each contain
        screenshot_id plus the CoordResult fields. Returns row count written.
        """
        fieldnames = ["screenshot_id", "lat", "lon", "coordinate_method",
                      "coordinate_confidence", "estimated_error_m", "in_pr_bbox"]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            count = 0
            for row in rows:
                lat = row.get("lat") or row.get("latitude") or 0.0
                lon = row.get("lon") or row.get("longitude") or 0.0
                in_bbox = (PR_BOUNDS["south"] <= lat <= PR_BOUNDS["north"] and
                           PR_BOUNDS["west"]  <= lon <= PR_BOUNDS["east"])
                writer.writerow({
                    "screenshot_id":         row.get("screenshot_id", ""),
                    "lat":                   lat,
                    "lon":                   lon,
                    "coordinate_method":     row.get("coordinate_method", "fixed_pr_bounds"),
                    "coordinate_confidence": row.get("coordinate_confidence", 0.65),
                    "estimated_error_m":     row.get("estimated_error_m", 1500.0),
                    "in_pr_bbox":            in_bbox,
                })
                count += 1
        return count

    def _fixed_pr_bounds(self, px: float, py: float,
                         img_w: int, img_h: int):
        map_top_px    = img_h * MAP_TOP_FRACTION
        map_bottom_px = img_h * MAP_BOTTOM_FRACTION
        map_h         = map_bottom_px - map_top_px
        if map_h <= 0 or img_w <= 0:
            return 0.0, 0.0
        rel_y = (py - map_top_px) / map_h
        rel_x = px / img_w
        lat = PR_BOUNDS["north"] - rel_y * (PR_BOUNDS["north"] - PR_BOUNDS["south"])
        lon = PR_BOUNDS["west"]  + rel_x * (PR_BOUNDS["east"]  - PR_BOUNDS["west"])
        return lat, lon

    def _anchor_interpolate(self, px: float, py: float,
                            img_w: int, img_h: int):
        if not self._anchors:
            return self._fixed_pr_bounds(px, py, img_w, img_h)

        rel_x = px / max(img_w, 1)
        rel_y = py / max(img_h, 1)

        # Inverse-distance weighting from all anchors in pixel-fraction space
        weights = []
        for a in self._anchors:
            dx = rel_x - a.pixel_x_fraction
            dy = rel_y - a.pixel_y_fraction
            dist = math.sqrt(dx * dx + dy * dy)
            weights.append(1.0 / (dist + 1e-9))

        total = sum(weights)
        lat = sum(w * a.lat for w, a in zip(weights, self._anchors)) / total
        lon = sum(w * a.lon for w, a in zip(weights, self._anchors)) / total
        return lat, lon

    @staticmethod
    def _load_anchors(csv_path: str) -> List[_Anchor]:
        anchors = []
        try:
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    anchors.append(_Anchor(
                        anchor_id=row["anchor_id"],
                        name=row["name"],
                        pixel_x_fraction=float(row["pixel_x_fraction"]),
                        pixel_y_fraction=float(row["pixel_y_fraction"]),
                        lat=float(row["lat"]),
                        lon=float(row["lon"]),
                    ))
        except (FileNotFoundError, KeyError, ValueError):
            pass
        return anchors


if __name__ == "__main__":
    cal = GeoCalibration(mode="fixed_pr_bounds")
    result = cal.pixel_to_coord(500, 300, 1024, 768)
    print(f"fixed_pr_bounds: {result}")

    cal2 = GeoCalibration(mode="airport_anchor")
    result2 = cal2.pixel_to_coord(500, 300, 1024, 768)
    print(f"airport_anchor:  {result2}")
