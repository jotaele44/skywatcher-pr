import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)

METRES_PER_DEGREE = 111_000.0  # approximate
MIN_HORIZONTAL_DIST_M = 1.0    # skip pairs closer than 1 m to avoid division by near-zero


def compute_slope(df: pd.DataFrame, elevation_col: str = 'elevation_proxy') -> pd.DataFrame:
    """Compute slope (rise/run, dimensionless) from an elevation column.

    Uses first-order central finite differences along the sorted spatial
    sequence (lat, lon).  Slope is computed as |Δz| / horizontal_distance,
    where horizontal_distance is the Euclidean distance between the two
    bracketing points projected to metres.

    Pairs whose bracketing horizontal distance is < MIN_HORIZONTAL_DIST_M
    are assigned slope = 0 to avoid division-by-near-zero artefacts that
    appear when many sorted points share the same latitude (e.g. regular
    DEM grids).

    Adds: slope (dimensionless, ≥ 0).
    """
    df = df.copy()

    if elevation_col not in df.columns:
        logger.warning(f"Column '{elevation_col}' not found – setting slope=0")
        df['slope'] = 0.0
        return df

    df_work = df.sort_values(['lat', 'lon']).copy()
    elevation = df_work[elevation_col].fillna(0.0).values.astype(float)
    lat       = df_work['lat'].values.astype(float)
    lon       = df_work['lon'].values.astype(float)

    n = len(elevation)
    slope_values = np.zeros(n, dtype=float)

    for i in range(1, n - 1):
        dz      = elevation[i + 1] - elevation[i - 1]
        dlat_m  = (lat[i + 1] - lat[i - 1]) * METRES_PER_DEGREE
        dlon_m  = (lon[i + 1] - lon[i - 1]) * METRES_PER_DEGREE * np.cos(np.radians(lat[i]))
        horiz_m = np.sqrt(dlat_m ** 2 + dlon_m ** 2)

        if horiz_m >= MIN_HORIZONTAL_DIST_M:
            slope_values[i] = abs(dz) / horiz_m
        else:
            slope_values[i] = 0.0

    if n >= 2:
        slope_values[0]     = slope_values[1]
        slope_values[n - 1] = slope_values[n - 2]
    elif n == 1:
        slope_values[0] = 0.0

    df_work['slope'] = slope_values
    df['slope'] = df_work['slope'].reindex(df.index).fillna(0.0)

    logger.info(
        f"Slope: mean={df['slope'].mean():.6f}, max={df['slope'].max():.6f}"
    )
    return df


def classify_slope(df: pd.DataFrame) -> pd.DataFrame:
    """Categorise slope magnitude into terrain classes.

    Adds: slope_class ('flat' | 'gentle' | 'moderate' | 'steep' | 'very_steep').
    """
    df = df.copy()

    if 'slope' not in df.columns:
        df['slope_class'] = 'unknown'
        return df

    def _classify(s: float) -> str:
        if s < 0.01:
            return 'flat'
        elif s < 0.05:
            return 'gentle'
        elif s < 0.15:
            return 'moderate'
        elif s < 0.30:
            return 'steep'
        else:
            return 'very_steep'

    df['slope_class'] = df['slope'].apply(_classify)
    return df
