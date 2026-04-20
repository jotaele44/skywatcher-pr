import logging
import os

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Minimum points required to run LOF and DBSCAN (both need at least 2)
_MIN_POINTS_LOF = 3
_MIN_POINTS_DBSCAN = 3

# Final score weights (mirrors run_temporal_clustering.py)
_FINAL_SCORE_WEIGHTS = {
    "physics_score": 0.30,
    "confidence": 0.25,
    "composite_score": 0.20,
    "persistence": 0.15,
    "spatial_anomaly_score": 0.10,
}

# Required columns in output (matches final_anomaly_ranked.csv schema)
_OUTPUT_COLUMNS = [
    "lat", "lon", "cell_id", "physics_score", "slope", "hydro_align",
    "classification", "confidence", "persistence", "cluster", "final_score",
    "composite_score", "spatial_anomaly_score",
]


def run_aoi_pipeline(raw_dir: str, aoi_id: str) -> pd.DataFrame:
    """
    Ingest GeoTIFFs from raw_dir and run the full physics + attribution pipeline
    scoped to those files only.

    Reuses all existing pipeline functions directly without modifying them.
    Sets persistence=1 for all rows (fresh satellite data, no snapshot history).

    Parameters
    ----------
    raw_dir : absolute path containing downloaded GeoTIFF files
    aoi_id  : 8-char hex identifier (used for logging)

    Returns
    -------
    pd.DataFrame compatible with final_anomaly_ranked.csv schema.
    Returns empty DataFrame with correct columns if raw_dir has no usable files.
    """
    # --- Step 1: Ingest ---
    df = _ingest(raw_dir)
    if df.empty:
        logger.warning("AOI pipeline [%s]: no data ingested from %s.", aoi_id, raw_dir)
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    logger.info("AOI pipeline [%s]: %d points ingested.", aoi_id, len(df))

    # --- Step 2: Physics ---
    df = _run_physics(df)

    # --- Step 3: Attribution ---
    df = _run_attribution(df)

    # --- Step 4: Clustering ---
    df = _run_clustering(df)

    # --- Step 5: Final score ---
    df["persistence"] = 1
    df["final_score"] = _compute_final_score(df)

    # Ensure required columns exist (fill missing with defaults)
    for col in _OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = 0

    logger.info(
        "AOI pipeline [%s]: complete. %d rows, %d ILAPs.",
        aoi_id, len(df),
        (df["classification"] == "anomaly").sum() if "classification" in df.columns else 0,
    )
    return df


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------

def _ingest(raw_dir: str) -> pd.DataFrame:
    """Scan raw_dir, dispatch files, unify into a single DataFrame."""
    from core.ingest.detect import scan_directory
    from core.ingest.dispatcher import dispatch_file
    from core.ingest.unify import unify_dataframes
    from core.ingest.crs import ensure_crs_columns, validate_latlon_range
    from core.ingest.raster_features import extract_raster_statistics
    from core.ingest.grid_align import assign_cell_id

    file_list = scan_directory(raw_dir)
    if not file_list:
        return pd.DataFrame()

    all_frames = []
    for filepath, _ in file_list:
        frames = dispatch_file(filepath)
        all_frames.extend(frames)

    if not all_frames:
        return pd.DataFrame()

    df = unify_dataframes(all_frames)
    df = ensure_crs_columns(df)
    df = validate_latlon_range(df)
    df = extract_raster_statistics(df)
    df = assign_cell_id(df)
    return df


def _run_physics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply terrain, slope, hydrology, and physics scoring.

    If DEM rows are present (source_file contains 'dem_'), real elevation
    is interpolated onto the analysis points via KNN and
    apply_terrain_constraints() is skipped (which would overwrite with
    synthetic values). Otherwise the full synthetic path runs unchanged.
    """
    from core.physics.slope import compute_slope, classify_slope
    from core.physics.hydrology import compute_hydrology_alignment, compute_drainage_index
    from core.physics.constraint_engine import compute_physics_score

    try:
        dem_mask = _dem_mask(df)

        if dem_mask.any() and (~dem_mask).any():
            # Real DEM path: interpolate elevation, drop DEM-only rows
            df = _apply_dem_elevation(df, dem_mask)
            logger.info("Using real DEM elevation for physics scoring.")
        else:
            # Synthetic fallback (no DEM data available)
            from core.physics.terrain_bathy_engine import apply_terrain_constraints
            df = df[~dem_mask].copy() if dem_mask.any() else df
            df = apply_terrain_constraints(df)
            logger.info("Using synthetic elevation proxy (no DEM data).")

        df = compute_slope(df)
        df = classify_slope(df)
        df = compute_hydrology_alignment(df)
        df = compute_drainage_index(df)
        df = compute_physics_score(df)

    except Exception as exc:
        logger.warning("Physics step failed (%s); filling defaults.", exc)
        for col, val in [("physics_score", 0.0), ("slope", 0.0), ("hydro_align", 0.0)]:
            if col not in df.columns:
                df[col] = val

    return df


def _dem_mask(df: pd.DataFrame) -> "pd.Series":
    """Return boolean Series identifying DEM-sourced rows."""
    if "source_file" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["source_file"].astype(str).str.contains("dem_", case=False, na=False)


def _apply_dem_elevation(df: pd.DataFrame, dem_mask: "pd.Series") -> pd.DataFrame:
    """
    KNN-interpolate real DEM elevation onto analysis (non-DEM) points.

    Uses sklearn KNeighborsRegressor (k=3, distance-weighted) to assign
    an elevation_proxy value to each analysis point from the nearest DEM
    sample pixels. Also sets terrain_valid and bathymetry_proxy.

    DEM rows are dropped before returning — they are reference data only.
    """
    from sklearn.neighbors import KNeighborsRegressor

    dem_df = df[dem_mask]
    analysis_df = df[~dem_mask].copy()

    n_neighbors = min(3, len(dem_df))
    knn = KNeighborsRegressor(n_neighbors=n_neighbors, weights="distance")
    knn.fit(dem_df[["lat", "lon"]].values, dem_df["raster_value"].values)

    elevations = knn.predict(analysis_df[["lat", "lon"]].values)
    analysis_df["elevation_proxy"] = elevations
    # Bathymetry proxy: negative elevation for below-sea-level points
    analysis_df["bathymetry_proxy"] = np.where(elevations < 0, elevations, 0.0)
    analysis_df["terrain_valid"] = (elevations >= -500) & (elevations <= 8849)

    logger.info(
        "DEM elevation applied: %.1f–%.1f m range across %d points.",
        float(elevations.min()), float(elevations.max()), len(analysis_df),
    )
    return analysis_df


def _run_attribution(df: pd.DataFrame) -> pd.DataFrame:
    """Classify observations, compute confidence, and spatial anomaly scores."""
    from core.attribution.anomaly_attribution import (
        classify_observations,
        compute_confidence,
        rank_anomalies,
    )
    from core.attribution.advanced_attribution import (
        compute_spatial_anomaly_score,
        compute_composite_attribution_score,
    )

    try:
        df = classify_observations(df)
        df = compute_confidence(df)
        df = rank_anomalies(df)
    except Exception as exc:
        logger.warning("Basic attribution failed (%s); using defaults.", exc)
        if "classification" not in df.columns:
            df["classification"] = "noise"
        if "confidence" not in df.columns:
            df["confidence"] = 0.0

    if len(df) >= _MIN_POINTS_LOF:
        try:
            df = compute_spatial_anomaly_score(df)
            df = compute_composite_attribution_score(df)
        except Exception as exc:
            logger.warning("Advanced attribution failed (%s); filling zeros.", exc)
            if "spatial_anomaly_score" not in df.columns:
                df["spatial_anomaly_score"] = 0.0
            if "composite_score" not in df.columns:
                df["composite_score"] = 0.0
    else:
        df["spatial_anomaly_score"] = 0.0
        df["composite_score"] = 0.0

    return df


def _run_clustering(df: pd.DataFrame) -> pd.DataFrame:
    """Run DBSCAN spatial clustering."""
    from core.clustering.spatial_cluster import run_dbscan_clustering, compute_cluster_statistics

    if len(df) >= _MIN_POINTS_DBSCAN:
        try:
            df = run_dbscan_clustering(df)
            df = compute_cluster_statistics(df)
        except Exception as exc:
            logger.warning("Clustering failed (%s); assigning all to noise.", exc)
            df["cluster"] = -1
            df["cluster_size"] = 1
    else:
        df["cluster"] = -1
        df["cluster_size"] = len(df)

    return df


def _compute_final_score(df: pd.DataFrame) -> pd.Series:
    """Compute weighted final score, matching run_temporal_clustering.py formula."""
    score = pd.Series(0.0, index=df.index)
    for col, weight in _FINAL_SCORE_WEIGHTS.items():
        if col in df.columns:
            score += weight * pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return np.clip(score, 0.0, 1.0)
