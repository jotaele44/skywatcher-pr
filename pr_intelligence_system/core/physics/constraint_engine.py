import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


def compute_physics_score(df: pd.DataFrame) -> pd.DataFrame:
    """Compute a combined physics constraint score for every row.

    Formula hierarchy (highest available wins):

    6-component (real bathymetry + TWI + drainage):
        slope_norm       18 %
        hydro_align      22 %
        elev_score       12 %
        twi_score        22 %
        drainage_score   12 %
        bathy_score      14 %   — shelf depth from NOAA multibeam

    5-component (TWI + drainage, no bathymetry):
        slope_norm       20 %
        hydro_align      25 %
        elev_score       15 %
        twi_score        25 %
        drainage_score   15 %

    3-component legacy fallback (no TWI / drainage):
        slope_norm       35 %
        hydro_align      40 %
        elev_score       25 %

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

    has_twi      = 'twi'              in df.columns
    has_drainage = 'drainage_index'   in df.columns
    has_bathy    = (
        'bathymetry_proxy' in df.columns
        and df['bathymetry_proxy'].std() > 0.5
    )

    if has_twi and has_drainage:
        twi_raw        = df['twi'].fillna(0.0).values.astype(float)
        drain_raw      = df['drainage_index'].fillna(0.0).values.astype(float)
        twi_score      = np.clip(twi_raw / 15.0, 0.0, 1.0)
        drainage_score = np.clip(drain_raw, 0.0, 1.0)

        if has_bathy:
            # Shallow continental shelf (0–200 m) scores higher than deep trench;
            # normalised against PR Trench maximum (~8 400 m).
            bathy_raw   = df['bathymetry_proxy'].fillna(0.0).values.astype(float)
            bathy_score = np.clip(1.0 - np.abs(bathy_raw) / 8400.0, 0.0, 1.0)

            physics_score = np.clip(
                0.18 * slope_norm
                + 0.22 * hydro
                + 0.12 * elev_score
                + 0.22 * twi_score
                + 0.12 * drainage_score
                + 0.14 * bathy_score,
                0.0, 1.0,
            )
            logger.info("physics_score: 6-component formula (real bathymetry)")
        else:
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
