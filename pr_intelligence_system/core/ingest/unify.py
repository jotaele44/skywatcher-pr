import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ['lat', 'lon']


def unify_dataframes(dataframes: list) -> pd.DataFrame:
    """Concatenate a list of DataFrames into a single unified DataFrame.

    Ensures 'lat' and 'lon' columns are present, drops rows where both
    are missing, and resets the index.
    """
    if not dataframes:
        logger.warning("No DataFrames provided to unify – returning empty DataFrame")
        return pd.DataFrame(columns=REQUIRED_COLUMNS + ['source_file', 'source_format'])

    unified = pd.concat(dataframes, ignore_index=True, sort=False)

    # Ensure required columns exist
    for col in REQUIRED_COLUMNS:
        if col not in unified.columns:
            logger.warning(f"Required column '{col}' missing – filling with NaN")
            unified[col] = np.nan

    # Drop rows with missing spatial coordinates
    before = len(unified)
    unified = unified.dropna(subset=['lat', 'lon']).reset_index(drop=True)
    after = len(unified)

    if before != after:
        logger.info(f"Dropped {before - after} rows with missing lat/lon")

    logger.info(
        f"Unified DataFrame: {len(unified)} rows × {len(unified.columns)} columns"
    )
    return unified
