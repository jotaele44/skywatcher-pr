import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


def extract_raster_statistics(df: pd.DataFrame, value_column: str = 'raster_value') -> pd.DataFrame:
    """Compute global statistics over a raster-value column and add them as new columns.

    Adds: raster_mean, raster_std, raster_normalized.
    """
    df = df.copy()

    if value_column not in df.columns:
        logger.warning(
            f"Column '{value_column}' not found – skipping raster statistics; "
            "filling with NaN"
        )
        df['raster_mean']       = np.nan
        df['raster_std']        = np.nan
        df['raster_normalized'] = np.nan
        return df

    values = pd.to_numeric(df[value_column], errors='coerce').dropna()

    if len(values) == 0:
        df['raster_mean']       = np.nan
        df['raster_std']        = np.nan
        df['raster_normalized'] = np.nan
        return df

    mean_val = float(values.mean())
    std_val  = float(values.std())

    df['raster_mean'] = mean_val
    df['raster_std']  = std_val

    if std_val > 0.0:
        df['raster_normalized'] = (
            pd.to_numeric(df[value_column], errors='coerce') - mean_val
        ) / std_val
    else:
        df['raster_normalized'] = 0.0

    logger.info(
        f"Raster statistics: mean={mean_val:.4f}, std={std_val:.4f}, "
        f"n_valid={len(values)}"
    )
    return df


def compute_raster_gradient(df: pd.DataFrame, value_column: str = 'raster_value') -> pd.DataFrame:
    """Approximate spatial gradient magnitude of raster values (sorted by lat, lon).

    Adds: raster_gradient.
    """
    df = df.copy()

    if value_column not in df.columns or len(df) < 2:
        df['raster_gradient'] = 0.0
        return df

    df_sorted = df.sort_values(['lat', 'lon']).copy()
    df_sorted['raster_gradient'] = (
        pd.to_numeric(df_sorted[value_column], errors='coerce')
        .diff()
        .fillna(0.0)
        .abs()
    )

    df['raster_gradient'] = df_sorted['raster_gradient'].reindex(df.index).fillna(0.0)
    return df
