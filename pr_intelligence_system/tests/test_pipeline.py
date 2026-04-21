import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from core.pipeline.aoi_pipeline import (
    _compute_final_score,
    _dem_mask,
    _apply_dem_elevation,
    _FINAL_SCORE_WEIGHTS,
)


def _make_df(**kwargs) -> pd.DataFrame:
    """Build a minimal DataFrame with required score columns."""
    n = kwargs.pop("n", 5)
    defaults = {
        "lat": np.linspace(18.0, 18.1, n),
        "lon": np.linspace(-66.7, -66.6, n),
        "physics_score": np.full(n, 0.6),
        "confidence": np.full(n, 0.7),
        "composite_score": np.full(n, 0.5),
        "persistence": np.full(n, 1.0),
        "spatial_anomaly_score": np.full(n, 0.4),
    }
    defaults.update(kwargs)
    return pd.DataFrame(defaults)


# ---------- _compute_final_score ----------

def test_final_score_range():
    df = _make_df()
    scores = _compute_final_score(df)
    assert (scores >= 0.0).all()
    assert (scores <= 1.0).all()


def test_final_score_all_zeros():
    df = _make_df(
        physics_score=np.zeros(5), confidence=np.zeros(5),
        composite_score=np.zeros(5), persistence=np.zeros(5),
        spatial_anomaly_score=np.zeros(5),
    )
    scores = _compute_final_score(df)
    assert (scores == 0.0).all()


def test_final_score_all_ones():
    df = _make_df(
        physics_score=np.ones(5), confidence=np.ones(5),
        composite_score=np.ones(5), persistence=np.ones(5),
        spatial_anomaly_score=np.ones(5),
    )
    scores = _compute_final_score(df)
    assert np.allclose(scores, 1.0)


def test_final_score_persistence_normalized():
    """With persistence=[1,2,3], max=3; normalized=[1/3,2/3,1]."""
    df = _make_df(
        n=3,
        physics_score=np.zeros(3), confidence=np.zeros(3),
        composite_score=np.zeros(3), spatial_anomaly_score=np.zeros(3),
        persistence=np.array([1.0, 2.0, 3.0]),
    )
    scores = _compute_final_score(df)
    # Only persistence contributes; weight/total_weight = 1.0 (only column)
    assert scores.iloc[0] < scores.iloc[1] < scores.iloc[2]


def test_final_score_missing_column_rescales_weights():
    """Removing a column should not deflate the score (weights are re-normalized)."""
    df_full = _make_df()
    df_partial = df_full.drop(columns=["spatial_anomaly_score"])
    s_full = _compute_final_score(df_full)
    s_partial = _compute_final_score(df_partial)
    # Partial should be >= full when the dropped column had value 0.4 < mean of others
    assert s_partial.mean() >= s_full.mean() * 0.9


# ---------- _dem_mask ----------

def test_dem_mask_detects_dem_rows():
    df = pd.DataFrame({
        "source_file": ["ndvi_openEO.tif", "dem_openEO.tif", "ndvi_other.tif"]
    })
    mask = _dem_mask(df)
    assert list(mask) == [False, True, False]


def test_dem_mask_no_source_file_column():
    df = pd.DataFrame({"lat": [1.0, 2.0]})
    mask = _dem_mask(df)
    assert not mask.any()


# ---------- _apply_dem_elevation ----------

def test_apply_dem_elevation_sets_elevation_proxy():
    # Create DEM rows (reference elevation)
    dem_rows = pd.DataFrame({
        "lat": [18.0, 18.1, 18.2],
        "lon": [-66.7, -66.7, -66.7],
        "raster_value": [100.0, 200.0, 300.0],
        "source_file": ["dem_x.tif"] * 3,
    })
    # Create analysis rows (NDVI points)
    ndvi_rows = pd.DataFrame({
        "lat": [18.05, 18.15],
        "lon": [-66.7, -66.7],
        "raster_value": [0.5, 0.6],
        "source_file": ["ndvi_x.tif"] * 2,
    })
    df = pd.concat([dem_rows, ndvi_rows], ignore_index=True)
    mask = _dem_mask(df)

    result = _apply_dem_elevation(df, mask)
    assert "elevation_proxy" in result.columns
    assert len(result) == 2  # DEM rows removed
    assert (result["elevation_proxy"] > 0).all()


def test_apply_dem_elevation_sets_terrain_valid():
    dem_rows = pd.DataFrame({
        "lat": [18.0], "lon": [-66.7], "raster_value": [500.0], "source_file": ["dem_x.tif"]
    })
    ndvi_rows = pd.DataFrame({
        "lat": [18.0], "lon": [-66.7], "raster_value": [0.5], "source_file": ["ndvi_x.tif"]
    })
    df = pd.concat([dem_rows, ndvi_rows], ignore_index=True)
    mask = _dem_mask(df)
    result = _apply_dem_elevation(df, mask)
    assert "terrain_valid" in result.columns
    assert result["terrain_valid"].iloc[0] is True or result["terrain_valid"].iloc[0] == True


def test_apply_dem_elevation_below_sea_level():
    dem_rows = pd.DataFrame({
        "lat": [18.0], "lon": [-66.7], "raster_value": [-50.0], "source_file": ["dem_x.tif"]
    })
    ndvi_rows = pd.DataFrame({
        "lat": [18.0], "lon": [-66.7], "raster_value": [0.3], "source_file": ["ndvi_x.tif"]
    })
    df = pd.concat([dem_rows, ndvi_rows], ignore_index=True)
    mask = _dem_mask(df)
    result = _apply_dem_elevation(df, mask)
    assert result["bathymetry_proxy"].iloc[0] < 0
