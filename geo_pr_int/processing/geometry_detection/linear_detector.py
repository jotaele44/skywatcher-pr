"""
Linear corridor detection for GEO-PR-INT.

Clusters ILAP candidates using DBSCAN in EPSG:32161 (Puerto Rico State Plane,
metres) and computes linearity R² for each cluster.  Clusters exceeding the
R² threshold are promoted to corridor candidates.
"""

import logging

import numpy as np
import pandas as pd

from config import SETTINGS
from utils.geo_helpers import df_to_epsg32161, linearity_r2, corridor_bearing_deg

logger = logging.getLogger(__name__)

_DET = SETTINGS["detection"]
_DEFAULT_EPS_M     = float(_DET["dbscan_eps_m"])
_DEFAULT_SAMPLES   = int(_DET["dbscan_min_samples"])
_DEFAULT_MIN_R2    = float(_DET["linearity_min_r2"])


def detect_linear_clusters(
    df: pd.DataFrame,
    eps_m: float = _DEFAULT_EPS_M,
    min_samples: int = _DEFAULT_SAMPLES,
) -> pd.DataFrame:
    """
    Run DBSCAN on candidates in EPSG:32161 space.

    Parameters
    ----------
    df         : DataFrame with lat, lon columns
    eps_m      : DBSCAN neighbourhood radius in metres
    min_samples: minimum cluster size

    Returns
    -------
    df with added column cluster_id (-1 = noise)
    """
    try:
        from sklearn.cluster import DBSCAN
    except ImportError:
        logger.warning("scikit-learn not installed — cluster_id set to -1 for all rows")
        df = df.copy()
        df["cluster_id"] = -1
        return df

    if df.empty or "lat" not in df.columns or "lon" not in df.columns:
        df = df.copy()
        df["cluster_id"] = -1
        return df

    try:
        coords_m = df_to_epsg32161(df)
    except Exception as exc:
        logger.warning(f"EPSG:32161 transform failed ({exc}); using lat/lon degrees × 111320")
        lat_m = df["lat"].values * 111_320.0
        lon_m = df["lon"].values * 111_320.0 * np.cos(np.radians(18.2))
        coords_m = np.column_stack([lon_m, lat_m])

    db = DBSCAN(eps=eps_m, min_samples=min_samples, metric="euclidean", n_jobs=-1)
    labels = db.fit_predict(coords_m)

    df = df.copy()
    df["cluster_id"] = labels
    n_clusters = int((labels >= 0).sum() > 0 and labels.max() + 1)
    n_noise    = int((labels == -1).sum())
    logger.info(
        f"DBSCAN (eps={eps_m}m, min_samples={min_samples}): "
        f"{n_clusters} clusters, {n_noise} noise points"
    )
    return df


def compute_cluster_linearity(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each cluster_id ≥ 0, compute linearity_r2 and bearing_deg.
    Adds columns: linearity_r2, bearing_deg.
    Noise rows (cluster_id == -1) get linearity_r2=0.0, bearing_deg=0.0.
    """
    if "cluster_id" not in df.columns:
        df = df.copy()
        df["linearity_r2"] = 0.0
        df["bearing_deg"]  = 0.0
        return df

    df = df.copy()
    r2_map: dict[int, float] = {}
    bear_map: dict[int, float] = {}

    for cid, group in df[df["cluster_id"] >= 0].groupby("cluster_id"):
        lats = group["lat"].values.astype(float)
        lons = group["lon"].values.astype(float)
        r2_map[cid]   = linearity_r2(lats, lons)
        bear_map[cid] = corridor_bearing_deg(lats, lons)

    df["linearity_r2"] = df["cluster_id"].map(r2_map).fillna(0.0)
    df["bearing_deg"]  = df["cluster_id"].map(bear_map).fillna(0.0)
    return df


def filter_linear_corridors(
    df: pd.DataFrame,
    min_r2: float = _DEFAULT_MIN_R2,
) -> pd.DataFrame:
    """
    Mark rows as linear_corridor=True if their cluster's linearity_r2 ≥ min_r2.
    Noise rows and non-linear clusters get linear_corridor=False.
    """
    if "linearity_r2" not in df.columns:
        df = compute_cluster_linearity(df)

    df = df.copy()
    df["linear_corridor"] = (
        (df.get("cluster_id", pd.Series(-1, index=df.index)) >= 0)
        & (df["linearity_r2"] >= min_r2)
    )
    n_linear = int(df["linear_corridor"].sum())
    logger.info(
        f"Linear corridors (R²≥{min_r2}): {n_linear}/{len(df)} candidates qualify"
    )
    return df


def assign_corridor_id(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename cluster_id → corridor_id for linear clusters.
    Linear cluster N → corridor_id N+1 (1-based).
    Non-linear clusters and noise → corridor_id 0.
    """
    if "linear_corridor" not in df.columns:
        df = filter_linear_corridors(df)

    df = df.copy()
    if "cluster_id" not in df.columns:
        df["corridor_id"] = 0
        return df

    df["corridor_id"] = np.where(
        df["linear_corridor"],
        df["cluster_id"] + 1,
        0,
    ).astype(int)
    return df


def run_geometry_detection(
    df: pd.DataFrame,
    eps_m: float = _DEFAULT_EPS_M,
    min_samples: int = _DEFAULT_SAMPLES,
    min_r2: float = _DEFAULT_MIN_R2,
) -> pd.DataFrame:
    """
    Full geometry detection pipeline: cluster → linearity → filter → assign.

    Returns df with columns added:
        cluster_id, linearity_r2, bearing_deg, linear_corridor, corridor_id
    """
    df = detect_linear_clusters(df, eps_m=eps_m, min_samples=min_samples)
    df = compute_cluster_linearity(df)
    df = filter_linear_corridors(df, min_r2=min_r2)
    df = assign_corridor_id(df)
    return df
