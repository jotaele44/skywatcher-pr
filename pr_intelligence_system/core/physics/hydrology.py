import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


def compute_hydrology_alignment(df: pd.DataFrame) -> pd.DataFrame:
    """Compute a hydrological alignment score for each point.

    Score ∈ [0, 1] where 1 = strong hydrological flow alignment.
    The proxy combines coastal/low-elevation proximity (60 %) and
    slope-driven flow potential (40 %).

    In production this would be derived from a proper DEM flow-direction
    grid (D8/D-infinity algorithm).

    Adds: hydro_align.
    """
    df = df.copy()

    elevation = (
        df['elevation_proxy'].fillna(0.0).values.astype(float)
        if 'elevation_proxy' in df.columns
        else np.zeros(len(df))
    )
    slope = (
        df['slope'].fillna(0.0).values.astype(float)
        if 'slope' in df.columns
        else np.zeros(len(df))
    )

    # Points closer to sea level have higher coastal proximity score
    coastal_proximity = 1.0 / (1.0 + np.abs(elevation) / 100.0)

    # Flow potential increases with slope
    flow_potential = np.tanh(slope * 100.0)

    hydro_align = np.clip(
        coastal_proximity * 0.6 + flow_potential * 0.4,
        0.0,
        1.0,
    )

    df['hydro_align'] = hydro_align
    logger.info(f"Hydro alignment: mean={hydro_align.mean():.4f}, std={hydro_align.std():.4f}")
    return df


def compute_drainage_index(df: pd.DataFrame) -> pd.DataFrame:
    """Compute a normalised drainage-basin index from elevation.

    Index ∈ [0, 1] where 1 = lowest point in the dataset (outlet).

    Adds: drainage_index.
    """
    df = df.copy()

    if 'elevation_proxy' not in df.columns:
        df['drainage_index'] = 0.0
        return df

    elevation = df['elevation_proxy'].fillna(0.0).values.astype(float)
    elev_range = elevation.max() - elevation.min()

    if elev_range > 0.0:
        drainage_index = 1.0 - (elevation - elevation.min()) / elev_range
    else:
        drainage_index = np.zeros(len(elevation))

    df['drainage_index'] = drainage_index
    logger.info(f"Drainage index: mean={drainage_index.mean():.4f}")
    return df
