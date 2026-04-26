"""
Satellite data ingestion for GEO-PR-INT.

Wraps the pr_intelligence_system fetcher pipeline and also reads from its
pre-computed output CSV (final_anomaly_ranked.csv) so the unified system
can bootstrap without re-running the full satellite pipeline.
"""

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from config import PR_INT_PATH, SETTINGS, AOI

logger = logging.getLogger(__name__)

# Ensure pr_intelligence_system is importable
_PR_INT_ON_PATH = False


def _ensure_pr_int_on_path() -> bool:
    global _PR_INT_ON_PATH
    if _PR_INT_ON_PATH:
        return True
    path_str = str(PR_INT_PATH)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
    try:
        import core  # noqa: F401
        _PR_INT_ON_PATH = True
        return True
    except ImportError:
        logger.warning(
            f"pr_intelligence_system not importable from {PR_INT_PATH}. "
            "Satellite fetchers will return empty DataFrames."
        )
        return False


# Output columns we carry forward from pr_intelligence_system
_ILAP_COLS = [
    "lat", "lon", "cell_id",
    "elevation_proxy", "bathymetry_proxy",
    "slope", "hydro_align", "drainage_index", "twi",
    "physics_score", "classification", "confidence",
    "infra_type", "infra_corridor", "infra_priority_score",
    "infra_evidence_score", "infra_status",
    "flood_risk", "routing_cost",
    "ndvi", "sar_linear_score", "ndvi_disturbance_score", "moisture_anomaly_score",
    "spatial_anomaly_score", "composite_score",
    "anomaly_rank", "final_score",
    "cluster", "cluster_size",
    "source_file", "source_format", "acquisition_date",
]


def _default_date_range() -> tuple[str, str]:
    days = SETTINGS.get("satellite", {}).get("date_range_days", 30)
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    return str(start), str(end)


def load_pr_intelligence_output() -> pd.DataFrame:
    """Load the pre-computed ILAP candidates from pr_intelligence_system output."""
    csv_path = PR_INT_PATH / "data" / "output" / "final_anomaly_ranked.csv"
    if not csv_path.exists():
        logger.warning(f"pr_intelligence_system output not found at {csv_path}")
        return pd.DataFrame()

    try:
        df = pd.read_csv(csv_path, low_memory=False)
        logger.info(f"Loaded {len(df)} ILAP candidates from {csv_path}")
    except Exception as exc:
        logger.error(f"Failed to read pr_intelligence_system output: {exc}")
        return pd.DataFrame()

    # Keep only the columns we need, with graceful fallback for missing ones
    keep = [c for c in _ILAP_COLS if c in df.columns]
    df = df[keep].copy()
    for col in _ILAP_COLS:
        if col not in df.columns:
            df[col] = None

    return df[_ILAP_COLS]


def run_satellite_pipeline(aoi: tuple | None = None) -> pd.DataFrame:
    """Run the full pr_intelligence_system satellite pipeline and return candidates.

    This is the live path — slower but produces fresh data.
    Requires pr_intelligence_system dependencies to be installed.
    """
    if not _ensure_pr_int_on_path():
        return pd.DataFrame()

    if aoi is None:
        aoi = AOI

    date_range = _default_date_range()

    try:
        import subprocess
        import os

        run_all = PR_INT_PATH / "run_all.py"
        if not run_all.exists():
            logger.warning(f"run_all.py not found at {run_all}")
            return load_pr_intelligence_output()

        logger.info("Running pr_intelligence_system pipeline...")
        result = subprocess.run(
            [sys.executable, str(run_all)],
            cwd=str(PR_INT_PATH),
            capture_output=False,
            timeout=600,
        )
        if result.returncode != 0:
            logger.warning("pr_intelligence_system pipeline returned non-zero exit code")

        return load_pr_intelligence_output()

    except subprocess.TimeoutExpired:
        logger.warning("pr_intelligence_system pipeline timed out")
        return load_pr_intelligence_output()
    except Exception as exc:
        logger.error(f"Satellite pipeline failed: {exc}")
        return load_pr_intelligence_output()


def fetch_satellite_features(
    aoi: tuple | None = None,
    live: bool = False,
) -> pd.DataFrame:
    """Return ILAP candidate DataFrame for downstream processing.

    Parameters
    ----------
    aoi  : bounding box (min_lon, min_lat, max_lon, max_lat)
    live : if True, re-run the full satellite pipeline; otherwise load cached output

    Returns
    -------
    DataFrame with _ILAP_COLS columns (may be partial if output CSV is stale)
    """
    if live:
        df = run_satellite_pipeline(aoi)
    else:
        df = load_pr_intelligence_output()

    if len(df) == 0:
        logger.warning("No satellite features available")
        return pd.DataFrame(columns=_ILAP_COLS)

    # Apply AOI filter
    if aoi is None:
        aoi = AOI
    min_lon, min_lat, max_lon, max_lat = aoi
    mask = (
        df["lon"].between(min_lon, max_lon)
        & df["lat"].between(min_lat, max_lat)
    )
    df = df[mask].reset_index(drop=True)
    logger.info(f"Satellite features after AOI filter: {len(df)} rows")
    return df
