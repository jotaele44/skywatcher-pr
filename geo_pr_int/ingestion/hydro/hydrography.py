"""
Hydrography ingestion for GEO-PR-INT.

Loads hydrological features for Puerto Rico from pr_intelligence_system's
pre-computed output (TWI, hydro_align, drainage_index, flow_accumulation)
or synthesises them from elevation data as a fallback.

Provides:
  - Stream network nodes (is_stream == True from pr_int)
  - Hydro proximity scores per candidate
  - Karst zone flags
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from config import PR_INT_PATH, GEO_PR_INT_ROOT, AOI, SETTINGS

logger = logging.getLogger(__name__)

HYDRO_CACHE = GEO_PR_INT_ROOT / "data" / "cache" / "hydro" / "pr_hydro.csv"

# Columns we read from pr_intelligence_system enriched output
_HYDRO_COLS = [
    "lat", "lon", "cell_id",
    "elevation_proxy", "slope",
    "flow_direction", "flow_accumulation",
    "twi", "is_stream", "karst_zone", "karst_penalty",
    "hydro_align", "drainage_index", "river_basin",
]


def _load_from_pr_int_enriched() -> pd.DataFrame:
    """Load hydrology columns from pr_intelligence_system enriched CSV."""
    csv_path = PR_INT_PATH / "data" / "output" / "unified_features_enriched.csv"
    if not csv_path.exists():
        logger.debug(f"pr_int enriched CSV not found: {csv_path}")
        return pd.DataFrame()
    try:
        df = pd.read_csv(csv_path, usecols=lambda c: c in _HYDRO_COLS, low_memory=False)
        df = df.dropna(subset=["lat", "lon"])
        keep = [c for c in _HYDRO_COLS if c in df.columns]
        logger.info(f"Loaded {len(df)} hydro rows from pr_int enriched CSV")
        return df[keep]
    except Exception as exc:
        logger.warning(f"Failed to load pr_int enriched CSV: {exc}")
        return pd.DataFrame()


def _load_from_final_ranked() -> pd.DataFrame:
    """Load hydrology columns from pr_intelligence_system final output."""
    csv_path = PR_INT_PATH / "data" / "output" / "final_anomaly_ranked.csv"
    if not csv_path.exists():
        return pd.DataFrame()
    try:
        available = pd.read_csv(csv_path, nrows=0).columns.tolist()
        cols = [c for c in _HYDRO_COLS if c in available]
        if len(cols) < 3:
            return pd.DataFrame()
        df = pd.read_csv(csv_path, usecols=cols, low_memory=False)
        df = df.dropna(subset=["lat", "lon"])
        logger.info(f"Loaded {len(df)} hydro rows from pr_int final output")
        return df
    except Exception as exc:
        logger.warning(f"Failed to load pr_int final output for hydro: {exc}")
        return pd.DataFrame()


def _synthesise_hydro(aoi: tuple) -> pd.DataFrame:
    """Synthesise a coarse hydro grid when pr_intelligence_system output is absent."""
    min_lon, min_lat, max_lon, max_lat = aoi
    step = 0.02
    lons = np.arange(min_lon, max_lon, step)
    lats = np.arange(min_lat, max_lat, step)
    grid_lon, grid_lat = np.meshgrid(lons, lats)

    lat_flat = grid_lat.ravel()
    lon_flat = grid_lon.ravel()
    n = len(lat_flat)

    rng = np.random.RandomState(42)
    # Approximate: higher TWI near river valleys (lower elevation + low slope)
    elev = np.abs(np.sin(np.radians(lat_flat * 3))) * 400 + rng.normal(0, 30, n)
    slope = np.abs(np.gradient(elev)) + rng.exponential(0.05, n)
    twi = np.clip(5.0 - slope * 10 + rng.normal(0, 1, n), 1.0, 15.0)
    hydro_align = np.clip(twi / 15.0, 0.0, 1.0)
    is_stream = twi > 10.0
    karst_zone = (lon_flat < -66.8) & (lat_flat > 18.1) & (lat_flat < 18.6)

    df = pd.DataFrame({
        "lat":              lat_flat,
        "lon":              lon_flat,
        "elevation_proxy":  elev,
        "slope":            slope,
        "twi":              twi,
        "hydro_align":      hydro_align,
        "drainage_index":   np.clip(twi / 20.0, 0, 1),
        "flow_accumulation": (twi * 100).astype(int),
        "is_stream":        is_stream,
        "karst_zone":       karst_zone,
        "karst_penalty":    karst_zone.astype(float) * 0.5,
        "river_basin":      "synthetic",
    })
    logger.info(f"Synthesised {len(df)} hydro rows (fallback)")
    return df


def load_hydro_features(
    aoi: tuple | None = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Load hydrological feature grid for the PR AOI.

    Parameters
    ----------
    aoi       : bounding box; defaults to PR EEZ
    use_cache : load from disk cache if available

    Returns
    -------
    DataFrame with _HYDRO_COLS (or subset thereof)
    """
    if aoi is None:
        aoi = AOI

    HYDRO_CACHE.parent.mkdir(parents=True, exist_ok=True)

    if use_cache and HYDRO_CACHE.exists():
        try:
            df = pd.read_csv(HYDRO_CACHE)
            logger.info(f"Hydro: loaded {len(df)} rows from cache")
            return df
        except Exception:
            pass

    # Try pr_intelligence_system sources first
    df = _load_from_pr_int_enriched()
    if len(df) == 0:
        df = _load_from_final_ranked()
    if len(df) == 0:
        df = _synthesise_hydro(aoi)

    # AOI filter
    min_lon, min_lat, max_lon, max_lat = aoi
    df = df[
        df["lon"].between(min_lon, max_lon)
        & df["lat"].between(min_lat, max_lat)
    ].reset_index(drop=True)

    df.to_csv(HYDRO_CACHE, index=False)
    logger.info(f"Hydro: {len(df)} rows written to cache")
    return df


def compute_hydro_proximity(
    candidates: pd.DataFrame,
    hydro: pd.DataFrame,
    buffer_m: float | None = None,
) -> pd.DataFrame:
    """Add hydro_proximity_score to each candidate.

    Score = 1.0 if within buffer_m of a stream node, else attenuated by distance.
    """
    from scipy.spatial import cKDTree
    from utils.geo_helpers import metres_to_degrees_approx

    if buffer_m is None:
        buffer_m = float(SETTINGS["hydro"]["buffer_m"])

    candidates = candidates.copy()

    stream_nodes = hydro[hydro.get("is_stream", pd.Series(False, index=hydro.index)).fillna(False)]
    if len(stream_nodes) == 0:
        logger.warning("No stream nodes in hydro data — hydro_proximity_score set to 0")
        candidates["hydro_proximity_score"] = 0.0
        return candidates

    buffer_deg = metres_to_degrees_approx(buffer_m)
    tree = cKDTree(stream_nodes[["lat", "lon"]].values)
    dists, _ = tree.query(candidates[["lat", "lon"]].values, k=1)
    scores = np.clip(1.0 - (dists / buffer_deg), 0.0, 1.0)
    candidates["hydro_proximity_score"] = scores
    return candidates
