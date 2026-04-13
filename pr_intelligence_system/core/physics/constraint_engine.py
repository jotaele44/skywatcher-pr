import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


def compute_physics_score(df: pd.DataFrame) -> pd.DataFrame:
    """Compute a combined physics constraint score for every row.

    Components and weights:
        slope_norm  (normalised slope magnitude)   35 %
        hydro_align (hydrological alignment)       40 %
        elev_score  (proximity to sea level)       25 %

    Final score ∈ [0, 1]; higher = more physically consistent with a
    significant surface feature or anomaly.

    Adds: physics_score.
    """
    df = df.copy()

    # Ensure all required source columns are present
    if 'slope' not in df.columns:
        df['slope'] = 0.0
    if 'hydro_align' not in df.columns:
        df['hydro_align'] = 0.5
    if 'elevation_proxy' not in df.columns:
        df['elevation_proxy'] = 0.0

    slope     = df['slope'].fillna(0.0).values.astype(float)
    hydro     = df['hydro_align'].fillna(0.5).values.astype(float)
    elevation = df['elevation_proxy'].fillna(0.0).values.astype(float)

    # Normalise slope to [0, 1]
    slope_max  = float(np.max(slope)) if float(np.max(slope)) > 0.0 else 1.0
    slope_norm = slope / slope_max

    # Elevation score: points near sea level score higher
    abs_elev    = np.abs(elevation)
    elev_denom  = float(abs_elev.max()) + 1.0
    elev_score  = np.clip(1.0 - abs_elev / elev_denom, 0.0, 1.0)

    physics_score = np.clip(
        0.35 * slope_norm
        + 0.40 * hydro
        + 0.25 * elev_score,
        0.0,
        1.0,
    )

    df['physics_score'] = physics_score
    logger.info(
        f"Physics score: mean={physics_score.mean():.4f}, "
        f"std={physics_score.std():.4f}, "
        f"max={physics_score.max():.4f}"
    )
    return df


def apply_physics_filters(df: pd.DataFrame, min_physics_score: float = 0.0) -> pd.DataFrame:
    """Remove rows whose physics_score is below min_physics_score.

    With the default of 0.0 all rows are retained; raise the threshold
    to enforce a minimum plausibility cut.
    """
    df = df.copy()

    if 'physics_score' not in df.columns:
        logger.warning("physics_score column absent – skipping filter")
        return df

    before = len(df)
    df = df[df['physics_score'] >= min_physics_score].reset_index(drop=True)
    removed = before - len(df)

    logger.info(
        f"Physics filter (min={min_physics_score}): "
        f"removed {removed} rows, {len(df)} retained"
    )
    return df
