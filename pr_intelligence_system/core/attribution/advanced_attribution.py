import numpy as np
import pandas as pd
import logging
from sklearn.neighbors import LocalOutlierFactor

logger = logging.getLogger(__name__)


def compute_spatial_anomaly_score(df: pd.DataFrame) -> pd.DataFrame:
    """Compute a spatial anomaly score using Local Outlier Factor.

    Features used: lat, lon, and physics_score (if available).
    The LOF result (-1 = outlier, +1 = inlier) is transformed to a
    continuous score ∈ [0, 1].

    Adds: spatial_anomaly_score.
    """
    df = df.copy()

    if len(df) < 3:
        logger.warning("Too few points for LOF – spatial_anomaly_score set to 0.5")
        df['spatial_anomaly_score'] = 0.5
        return df

    feature_cols = ['lat', 'lon']
    if 'physics_score' in df.columns:
        feature_cols.append('physics_score')

    features = df[feature_cols].fillna(0.0).values.astype(float)

    n_neighbors = min(20, len(features) - 1)

    lof = LocalOutlierFactor(n_neighbors=n_neighbors, contamination=0.1)
    lof_labels = lof.fit_predict(features)

    # Negative outlier factor: larger (less negative) = more normal
    raw_lof = -lof.negative_outlier_factor_  # now positive; larger = more anomalous
    lof_min = raw_lof.min()
    lof_max = raw_lof.max()
    lof_range = lof_max - lof_min + 1e-10
    lof_norm = (raw_lof - lof_min) / lof_range  # [0, 1]; 1 = most anomalous

    # Base score from LOF label
    base_score = np.where(lof_labels == -1, 0.7, 0.3)

    spatial_anomaly_score = np.clip(
        base_score * 0.6 + lof_norm * 0.4,
        0.0,
        1.0,
    )

    df['spatial_anomaly_score'] = spatial_anomaly_score
    logger.info(
        f"Spatial anomaly score: mean={spatial_anomaly_score.mean():.4f}, "
        f"outliers={int((lof_labels == -1).sum())}"
    )
    return df


def compute_composite_attribution_score(df: pd.DataFrame) -> pd.DataFrame:
    """Fuse multiple attribution signals into a single composite score.

    Signal weights:
        physics_score         40 %
        spatial_anomaly_score 35 %
        confidence            25 %

    Weights are re-normalised if a signal column is absent.

    Adds: composite_score ∈ [0, 1].
    """
    df = df.copy()

    signal_weights = {
        'physics_score':        0.40,
        'spatial_anomaly_score': 0.35,
        'confidence':            0.25,
    }

    available = {
        col: weight
        for col, weight in signal_weights.items()
        if col in df.columns
    }

    if not available:
        logger.warning("No attribution signals available – composite_score set to 0.5")
        df['composite_score'] = 0.5
        return df

    total_weight = sum(available.values())
    composite = np.zeros(len(df), dtype=float)

    for col, weight in available.items():
        values = df[col].fillna(0.0).values.astype(float)
        composite += (weight / total_weight) * values

    df['composite_score'] = np.clip(composite, 0.0, 1.0)
    logger.info(
        f"Composite attribution score: mean={df['composite_score'].mean():.4f}, "
        f"signals used={list(available.keys())}"
    )
    return df
