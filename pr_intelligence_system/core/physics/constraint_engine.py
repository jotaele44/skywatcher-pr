import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


def compute_physics_score(df: pd.DataFrame) -> pd.DataFrame:
    """Compute a combined physics constraint score for every row.

    Weights (hydrography-backbone model):
        slope_norm       20 %  — terrain ruggedness
        hydro_align      25 %  — hydrological flow alignment (TWI-based if available)
        elev_score       15 %  — proximity to sea level
        twi_score        25 %  — Topographic Wetness Index (real hydrology signal)
        drainage_score   15 %  — upstream contributing area (flow accumulation)

    When TWI / drainage columns are absent (first run or synthetic data) the
    score falls back to the original three-component formula so the pipeline
    always produces a valid output.

    Final score ∈ [0, 1]; higher = stronger physical signature.

    Adds: physics_score.
    """
    df = df.copy()

    for col, default in [('slope', 0.0), ('hydro_align', 0.5),
                         ('elevation_proxy', 0.0)]:
        if col not in df.columns:
            df[col] = default

    slope     = df['slope'].fillna(0.0).values.astype(float)
    hydro     = df['hydro_align'].fillna(0.5).values.astype(float)
    elevation = df['elevation_proxy'].fillna(0.0).values.astype(float)

    slope_max  = float(np.max(slope)) if float(np.max(slope)) > 0.0 else 1.0
    slope_norm = slope / slope_max

    abs_elev   = np.abs(elevation)
    elev_denom = float(abs_elev.max()) + 1.0
    elev_score = np.clip(1.0 - abs_elev / elev_denom, 0.0, 1.0)

    has_twi      = 'twi'             in df.columns
    has_drainage = 'drainage_index'  in df.columns

    if has_twi and has_drainage:
        twi_raw   = df['twi'].fillna(0.0).values.astype(float)
        drain_raw = df['drainage_index'].fillna(0.0).values.astype(float)

        twi_score     = np.clip(twi_raw / 15.0, 0.0, 1.0)
        drainage_score = np.clip(drain_raw, 0.0, 1.0)

        physics_score = np.clip(
            0.20 * slope_norm
            + 0.25 * hydro
            + 0.15 * elev_score
            + 0.25 * twi_score
            + 0.15 * drainage_score,
            0.0, 1.0,
        )
        logger.info("physics_score: hydrography-backbone (5-component) formula")
    else:
        # Backward-compatible 3-component fallback
        physics_score = np.clip(
            0.35 * slope_norm + 0.40 * hydro + 0.25 * elev_score, 0.0, 1.0
        )
        logger.info("physics_score: legacy 3-component formula (no TWI/drainage)")

    df['physics_score'] = physics_score
    logger.info(
        f"Physics score: mean={physics_score.mean():.4f}, "
        f"std={physics_score.std():.4f}, max={physics_score.max():.4f}"
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
