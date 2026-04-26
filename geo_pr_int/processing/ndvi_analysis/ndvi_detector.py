"""
NDVI anomaly detection for GEO-PR-INT.

Derives NDVI scores from pr_intelligence_system columns (ndvi,
ndvi_disturbance_score) and flags anomalous vegetation disturbance
that may indicate subsurface construction or pipeline activity.
"""

import logging

import numpy as np
import pandas as pd

from config import SETTINGS

logger = logging.getLogger(__name__)

_NDVI_THRESHOLD = float(SETTINGS["detection"].get("ndvi_anomaly_threshold", -0.15))


def compute_ndvi_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Derive ndvi_score in [0, 1] from available columns.

    Priority:
      1. ndvi_disturbance_score (already normalised by pr_int)
      2. ndvi column: invert and scale (lower NDVI → higher disturbance score)
      3. Fill 0.0
    """
    df = df.copy()

    if "ndvi_disturbance_score" in df.columns:
        vals = pd.to_numeric(df["ndvi_disturbance_score"], errors="coerce").fillna(0.0)
        df["ndvi_score"] = vals.clip(0.0, 1.0)

    elif "ndvi" in df.columns:
        raw = pd.to_numeric(df["ndvi"], errors="coerce").fillna(0.3)
        # Typical healthy PR vegetation: NDVI ~0.4–0.8
        # Disturbed/cleared: NDVI ~0.0–0.2  → high disturbance score
        disturbance = np.clip(1.0 - (raw - _NDVI_THRESHOLD) / (0.8 - _NDVI_THRESHOLD), 0.0, 1.0)
        df["ndvi_score"] = disturbance

    else:
        df["ndvi_score"] = 0.0

    return df


def flag_ndvi_anomalies(
    df: pd.DataFrame,
    threshold: float = _NDVI_THRESHOLD,
) -> pd.DataFrame:
    """
    Add boolean ndvi_anomaly column.

    An anomaly is flagged when:
      - ndvi column is present and ndvi < threshold, OR
      - ndvi_disturbance_score > 0.5
    """
    df = df.copy()

    anomaly = pd.Series(False, index=df.index)

    if "ndvi" in df.columns:
        raw = pd.to_numeric(df["ndvi"], errors="coerce").fillna(0.3)
        anomaly |= (raw < threshold)

    if "ndvi_disturbance_score" in df.columns:
        dist = pd.to_numeric(df["ndvi_disturbance_score"], errors="coerce").fillna(0.0)
        anomaly |= (dist > 0.5)

    df["ndvi_anomaly"] = anomaly
    pct = float(anomaly.mean() * 100)
    logger.info(f"NDVI anomalies flagged: {anomaly.sum()} / {len(df)} ({pct:.1f}%)")
    return df


def compute_ndvi_trend(
    df: pd.DataFrame,
    time_col: str = "acquisition_date",
) -> pd.DataFrame:
    """
    Per-cell NDVI trend slope (using scipy linregress on date ordinals).

    Negative slope → vegetation degradation (higher suspicion).
    Adds ndvi_trend column; fills 0.0 when fewer than 3 distinct dates.
    """
    df = df.copy()

    if "ndvi" not in df.columns or time_col not in df.columns:
        df["ndvi_trend"] = 0.0
        return df

    try:
        from scipy.stats import linregress

        df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
        valid = df[df[time_col].notna()].copy()

        if valid[time_col].nunique() < 3:
            df["ndvi_trend"] = 0.0
            return df

        ordinal = valid[time_col].map(lambda d: d.toordinal()).astype(float)
        ndvi_vals = pd.to_numeric(valid["ndvi"], errors="coerce").fillna(0.3)

        try:
            slope = linregress(ordinal, ndvi_vals).slope
        except Exception:
            slope = 0.0

        df["ndvi_trend"] = slope

    except ImportError:
        logger.debug("scipy not available — ndvi_trend set to 0")
        df["ndvi_trend"] = 0.0
    except Exception as exc:
        logger.warning(f"NDVI trend computation failed: {exc}")
        df["ndvi_trend"] = 0.0

    return df


def ndvi_summary_stats(df: pd.DataFrame) -> dict:
    """Return dict with mean, std, pct_anomaly for NDVI fields."""
    out: dict = {}
    for col in ["ndvi", "ndvi_score", "ndvi_disturbance_score"]:
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").dropna()
            out[f"{col}_mean"] = float(vals.mean()) if len(vals) else 0.0
            out[f"{col}_std"]  = float(vals.std())  if len(vals) else 0.0

    if "ndvi_anomaly" in df.columns:
        out["pct_anomaly"] = float(df["ndvi_anomaly"].mean() * 100)
    return out


def run_ndvi_detection(df: pd.DataFrame) -> pd.DataFrame:
    """
    Full NDVI detection pipeline:
    1. Compute ndvi_score
    2. Flag anomalies
    3. Compute trend (if dates available)
    """
    df = compute_ndvi_score(df)
    df = flag_ndvi_anomalies(df)
    df = compute_ndvi_trend(df)
    stats = ndvi_summary_stats(df)
    logger.info(
        f"NDVI pipeline: score_mean={stats.get('ndvi_score_mean', 0):.3f}, "
        f"anomalies={stats.get('pct_anomaly', 0):.1f}%"
    )
    return df
