"""Geospatial utility functions for GEO-PR-INT."""

import math
from typing import Iterable

import numpy as np
import pandas as pd

# Puerto Rico municipality centroids (WGS-84, approximate)
PR_MUNICIPALITY_CENTROIDS: dict[str, tuple[float, float]] = {
    "san juan":      (18.4655, -66.1057),
    "bayamon":       (18.3794, -66.1635),
    "bayamón":       (18.3794, -66.1635),
    "carolina":      (18.3808, -65.9571),
    "ponce":         (17.9983, -66.6148),
    "caguas":        (18.2341, -65.9790),
    "guaynabo":      (18.3698, -66.1097),
    "arecibo":       (18.4720, -66.7160),
    "toa baja":      (18.4440, -66.2545),
    "mayaguez":      (18.2011, -67.1397),
    "mayagüez":      (18.2011, -67.1397),
    "humacao":       (18.1497, -65.8250),
    "aguadilla":     (18.4274, -67.1541),
    "fajardo":       (18.3256, -65.6527),
    "guayama":       (17.9843, -66.1148),
    "coamo":         (18.0788, -66.3589),
    "vega baja":     (18.4455, -66.3870),
    "manati":        (18.4285, -66.4868),
    "manatí":        (18.4285, -66.4868),
    "lares":         (18.2939, -66.8786),
    "yauco":         (18.0352, -66.8494),
    "penuelas":      (17.9883, -66.7227),
    "juana diaz":    (18.0527, -66.5074),
    "juana díaz":    (18.0527, -66.5074),
    "naranjito":     (18.2999, -66.2433),
    "utuado":        (18.2652, -66.6996),
    "isabela":       (18.5008, -67.0225),
    "camuy":         (18.4833, -66.8450),
    "rincon":        (18.3395, -67.2497),
    "rincón":        (18.3395, -67.2497),
    "cabo rojo":     (18.0868, -67.1459),
    "hormigueros":   (18.1390, -67.1254),
    "lajas":         (18.0519, -67.0597),
    "san german":    (18.0812, -67.0393),
    "san germán":    (18.0812, -67.0393),
    "sabana grande": (18.0780, -66.9616),
    "adjuntas":      (18.1626, -66.7231),
    "jayuya":        (18.2195, -66.5923),
    "ciales":        (18.3360, -66.4695),
    "orocovis":      (18.2273, -66.3926),
    "barranquitas":  (18.1869, -66.3065),
    "aibonito":      (18.1412, -66.2666),
    "cayey":         (18.1127, -66.1662),
    "cidra":         (18.1761, -66.1618),
    "aguas buenas":  (18.2575, -66.1027),
    "comerio":       (18.2195, -66.2268),
    "toa alta":      (18.3886, -66.2483),
    "dorado":        (18.4581, -66.2700),
    "vega alta":     (18.4118, -66.3286),
    "barceloneta":   (18.4482, -66.5392),
    "florida":       (18.3638, -66.5624),
    "hatillo":       (18.4862, -66.8243),
    "quebradillas":  (18.4741, -66.9388),
    "moca":          (18.3930, -67.1144),
    "aguada":        (18.3791, -67.1870),
    "anasco":        (18.2870, -67.1444),
    "añasco":        (18.2870, -67.1444),
    "san sebastian": (18.3357, -66.9869),
    "san sebastián": (18.3357, -66.9869),
    "las marias":    (18.2518, -66.9912),
    "las marías":    (18.2518, -66.9912),
    "maricao":       (18.1812, -66.9800),
    "guanica":       (17.9718, -66.9077),
    "guánica":       (17.9718, -66.9077),
    "salinas":       (17.9759, -66.2982),
    "santa isabel":  (17.9656, -66.4046),
    "villalba":      (18.1261, -66.4906),
    "patillas":      (18.0047, -66.0142),
    "arroyo":        (17.9667, -66.0613),
    "maunabo":       (18.0065, -65.8992),
    "yabucoa":       (18.0507, -65.8791),
    "juncos":        (18.2275, -65.9199),
    "las piedras":   (18.1834, -65.8679),
    "naguabo":       (18.2115, -65.7347),
    "ceiba":         (18.2647, -65.6481),
    "luquillo":      (18.3726, -65.7168),
    "rio grande":    (18.3803, -65.8327),
    "río grande":    (18.3803, -65.8327),
    "loiza":         (18.4313, -65.8778),
    "loíza":         (18.4313, -65.8778),
    "trujillo alto": (18.3558, -66.0173),
    "gurabo":        (18.2547, -65.9729),
    "san lorenzo":   (18.1887, -65.9699),
    "moca":          (18.3930, -67.1144),
    "canovanas":     (18.3783, -65.9008),
    "cataño":        (18.4380, -66.1319),
    "catano":        (18.4380, -66.1319),
    "puerto rico":   (18.2208, -66.5901),   # island centroid fallback
}

PR_CENTROID = (18.2208, -66.5901)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS-84 points."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def aoi_filter(df: pd.DataFrame, aoi: tuple) -> pd.DataFrame:
    """Filter DataFrame to bounding box (min_lon, min_lat, max_lon, max_lat)."""
    min_lon, min_lat, max_lon, max_lat = aoi
    mask = (
        df["lon"].between(min_lon, max_lon)
        & df["lat"].between(min_lat, max_lat)
    )
    return df[mask].reset_index(drop=True)


def geocode_place_name(name: str) -> tuple[float, float] | None:
    """Look up a PR municipality or place name and return (lat, lon) or None."""
    if not isinstance(name, str):
        return None
    key = name.lower().strip()
    # Direct match
    if key in PR_MUNICIPALITY_CENTROIDS:
        return PR_MUNICIPALITY_CENTROIDS[key]
    # Partial match
    for muni, coords in PR_MUNICIPALITY_CENTROIDS.items():
        if muni in key or key in muni:
            return coords
    return None


def degrees_to_metres_approx(deg: float, lat: float = 18.2) -> float:
    """Approximate conversion: degrees → metres at given latitude."""
    lat_m = 111_320.0
    lon_m = 111_320.0 * math.cos(math.radians(lat))
    return deg * (lat_m + lon_m) / 2.0


def metres_to_degrees_approx(metres: float, lat: float = 18.2) -> float:
    """Approximate conversion: metres → degrees at given latitude."""
    lat_m = 111_320.0
    lon_m = 111_320.0 * math.cos(math.radians(lat))
    return metres / ((lat_m + lon_m) / 2.0)


def linearity_r2(lats: np.ndarray, lons: np.ndarray) -> float:
    """Return R² of a linear regression lon~lat; 1.0 = perfect line."""
    from scipy.stats import linregress
    if len(lats) < 3:
        return 0.0
    try:
        result = linregress(lons, lats)
        return float(result.rvalue ** 2)
    except Exception:
        return 0.0


def corridor_bearing_deg(lats: np.ndarray, lons: np.ndarray) -> float:
    """Return the bearing (0–180°) of a linear corridor from its endpoints."""
    if len(lats) < 2:
        return 0.0
    i0 = int(np.argmin(lats))
    i1 = int(np.argmax(lats))
    dlat = lats[i1] - lats[i0]
    dlon = lons[i1] - lons[i0]
    return float(math.degrees(math.atan2(dlon, dlat)) % 180)


def to_wgs84_epsg32161(x_m: float, y_m: float) -> tuple[float, float]:
    """Convert EPSG:32161 (metres) → WGS-84 (lat, lon)."""
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:32161", "EPSG:4326", always_xy=True)
    lon, lat = t.transform(x_m, y_m)
    return float(lat), float(lon)


def to_epsg32161(lat: float, lon: float) -> tuple[float, float]:
    """Convert WGS-84 (lat, lon) → EPSG:32161 (x_m, y_m)."""
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:4326", "EPSG:32161", always_xy=True)
    x, y = t.transform(lon, lat)
    return float(x), float(y)


def df_to_epsg32161(df: pd.DataFrame) -> np.ndarray:
    """Transform all (lat, lon) rows to EPSG:32161 (N×2 metres array)."""
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:4326", "EPSG:32161", always_xy=True)
    lons = df["lon"].values.astype(float)
    lats = df["lat"].values.astype(float)
    xs, ys = t.transform(lons, lats)
    return np.column_stack([xs, ys])
