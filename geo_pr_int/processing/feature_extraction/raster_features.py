"""
Raster / satellite feature extraction for GEO-PR-INT.

Selects and normalises the relevant signal columns from ILAP candidate
DataFrames produced by pr_intelligence_system.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Columns produced by pr_intelligence_system that we use downstream
_SIGNAL_COLS = [
    "sar_linear_score",
    "ndvi_disturbance_score",
    "moisture_anomaly_score",
    "spatial_anomaly_score",
    "physics_score",
    "confidence",
    "composite_score",
    "final_score",
    "infra_priority_score",
    "hydro_align",
    "drainage_index",
    "twi",
    "slope",
    "elevation_proxy",
    "bathymetry_proxy",
]

# Composite signal weights (sum to 1.0)
_COMPOSITE_WEIGHTS = {
    "sar_linear_score":       0.30,
    "ndvi_disturbance_score": 0.25,
    "moisture_anomaly_score": 0.20,
    "spatial_anomaly_score":  0.25,
}


def extract_ilap_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Select and return only the signal columns present in df.
    Always preserves lat, lon, cell_id, and any infra/classification cols.
    """
    always_keep = ["lat", "lon", "cell_id", "classification", "infra_type",
                   "infra_corridor", "infra_status", "cluster", "cluster_size",
                   "anomaly_rank", "acquisition_date", "source_file"]
    keep = [c for c in always_keep if c in df.columns]
    keep += [c for c in _SIGNAL_COLS if c in df.columns and c not in keep]
    return df[keep].copy()


def normalise_scores(df: pd.DataFrame, cols: list[str] | None = None) -> pd.DataFrame:
    """Min-max normalise each column to [0, 1]. NaN-safe."""
    df = df.copy()
    if cols is None:
        cols = [c for c in _SIGNAL_COLS if c in df.columns]
    for col in cols:
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        lo, hi = series.min(), series.max()
        if pd.isna(lo) or pd.isna(hi) or hi == lo:
            df[col] = series.fillna(0.0)
        else:
            df[col] = ((series - lo) / (hi - lo)).fillna(0.0)
    return df


def compute_composite_signal(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add composite_signal column: weighted sum of the four primary SAR/NDVI signals.
    Falls back gracefully when columns are absent.
    """
    df = df.copy()
    total_w = 0.0
    signal = pd.Series(0.0, index=df.index)
    for col, w in _COMPOSITE_WEIGHTS.items():
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            signal = signal + vals * w
            total_w += w
    if total_w > 0:
        signal = (signal / total_w).clip(0.0, 1.0)
    df["composite_signal"] = signal
    return df


def bin_elevation_proxy(
    series: pd.Series,
    n_bins: int = 5,
) -> pd.Series:
    """
    Quantile-bin elevation_proxy into integer labels 0 (lowest) – n_bins-1 (highest).
    Returns 0 for NaN values.
    """
    numeric = pd.to_numeric(series, errors="coerce")
    try:
        binned = pd.qcut(numeric, q=n_bins, labels=False, duplicates="drop")
    except Exception:
        binned = pd.Series(0, index=series.index, dtype=int)
    return binned.fillna(0).astype(int)


def fill_missing_signal_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure every signal column exists, filling with 0.0 if absent."""
    df = df.copy()
    for col in _SIGNAL_COLS:
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Full feature preparation pipeline:
    1. Extract relevant columns
    2. Fill missing signals
    3. Normalise all signal columns
    4. Compute composite signal
    5. Bin elevation proxy
    """
    df = extract_ilap_features(df)
    df = fill_missing_signal_cols(df)
    df = normalise_scores(df)
    df = compute_composite_signal(df)
    if "elevation_proxy" in df.columns:
        df["elevation_bin"] = bin_elevation_proxy(df["elevation_proxy"])
    logger.info(
        f"Feature extraction: {len(df)} rows, "
        f"composite_signal mean={df.get('composite_signal', pd.Series([0])).mean():.3f}"
    )
    return df
