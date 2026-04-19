"""
Satellite-Based Infrastructure Validation — Puerto Rico
=========================================================
Validates which elements of the proposed subsurface infrastructure network
already exist by analysing signatures in multi-source satellite data:

  1. SAR linear anomaly  (Sentinel-1 VV backscatter)
     Disturbed/compacted soil over buried infrastructure has different
     backscatter than the surrounding undisturbed surface.

  2. NDVI disturbance corridor  (Sentinel-2 / Landsat)
     Freshly excavated and backfilled trenches show below-average NDVI
     (bare/disturbed soil strips) detectable for 1–3 years post-construction.

  3. Moisture anomaly  (NDWI + CHIRPS precipitation residual)
     Leaking pipes or high-permeability backfill create linear patterns
     of elevated near-surface moisture.

Evidence scores are fused into infra_evidence_score and a final
infra_status label: confirmed | suspected | proposed | absent.
"""

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
NBHD_RADIUS_DEG    = 0.05     # ~5.5 km spatial neighbourhood
MIN_NBHD_PTS       = 5        # minimum neighbours for z-score
NDWI_WET_THRESH    = 0.15     # NDWI above → moisture anomaly

# Evidence fusion weights
_W_EVIDENCE = {'sar': 0.40, 'ndvi': 0.35, 'moisture': 0.25}


def _local_zscores(values: np.ndarray, lat: np.ndarray, lon: np.ndarray,
                   radius_deg: float) -> np.ndarray:
    """Compute per-point z-score relative to spatial neighbourhood.

    Uses a simple radius-ball query so it is O(n × neighbourhood size).
    Capped at 3000 points for tractability.
    """
    from scipy.spatial import cKDTree

    n      = len(values)
    z      = np.zeros(n)
    pts    = np.column_stack([lat, lon])
    tree   = cKDTree(pts)

    indices = tree.query_ball_point(pts, radius_deg)
    for i in range(n):
        nbhd = [j for j in indices[i] if j != i]
        if len(nbhd) < MIN_NBHD_PTS:
            continue
        nb_vals = values[nbhd]
        mean_v  = float(nb_vals.mean())
        std_v   = float(nb_vals.std())
        z[i]    = (values[i] - mean_v) / (std_v + 1e-10)
    return z


def compute_sar_linear_score(df: pd.DataFrame) -> pd.DataFrame:
    """Detect linear backscatter anomalies in Sentinel-1 VV that indicate buried infrastructure.

    Adds: sar_linear_score (float [0, 1]).
    """
    df = df.copy()
    df['sar_linear_score'] = 0.0

    sar_mask = (df.get('source_format', pd.Series([''] * len(df))) == 'sentinel1_sar')
    n_sar    = int(sar_mask.sum())

    if n_sar < MIN_NBHD_PTS:
        logger.info(f"SAR linear score: {n_sar} SAR points (insufficient) – skipping")
        return df

    # Cap at 3000 points for tractability
    sar_idx = df.index[sar_mask]
    if n_sar > 3000:
        sar_idx = sar_idx[:3000]

    sar_sub = df.loc[sar_idx]
    lat_    = sar_sub['lat'].values.astype(float)
    lon_    = sar_sub['lon'].values.astype(float)
    val_    = sar_sub['raster_value'].fillna(0.0).values.astype(float)

    z      = _local_zscores(val_, lat_, lon_, NBHD_RADIUS_DEG)
    scores = np.clip(np.abs(z) / 3.0, 0.0, 1.0)

    df.loc[sar_idx, 'sar_linear_score'] = scores
    logger.info(
        f"SAR linear score: {n_sar} SAR points, mean={scores.mean():.3f}, "
        f"high (>0.5)={int((scores > 0.5).sum())}"
    )
    return df


def compute_ndvi_disturbance_score(df: pd.DataFrame) -> pd.DataFrame:
    """Detect below-average NDVI strips that indicate trench disturbance.

    Negative local NDVI z-score = bare/disturbed soil = evidence of recent trenching.

    Adds: ndvi_disturbance_score (float [0, 1]).
    """
    df = df.copy()
    df['ndvi_disturbance_score'] = 0.0

    if 'ndvi' not in df.columns:
        return df

    opt_mask = (
        df.get('source_format', pd.Series([''] * len(df))).isin(['sentinel2_optical', 'landsat_c2'])
        & df['ndvi'].notna()
    )
    n_opt = int(opt_mask.sum())

    if n_opt < MIN_NBHD_PTS:
        logger.info(f"NDVI disturbance: {n_opt} optical points (insufficient) – skipping")
        return df

    opt_idx = df.index[opt_mask]
    if n_opt > 3000:
        opt_idx = opt_idx[:3000]

    opt_sub = df.loc[opt_idx]
    lat_    = opt_sub['lat'].values.astype(float)
    lon_    = opt_sub['lon'].values.astype(float)
    ndvi_   = opt_sub['ndvi'].values.astype(float)

    z         = _local_zscores(ndvi_, lat_, lon_, NBHD_RADIUS_DEG)
    disturb   = np.clip(-z / 3.0, 0.0, 1.0)   # negative z = below-average NDVI = disturbed

    df.loc[opt_idx, 'ndvi_disturbance_score'] = disturb
    logger.info(
        f"NDVI disturbance: {n_opt} optical points, mean={disturb.mean():.3f}"
    )
    return df


def compute_moisture_anomaly_score(df: pd.DataFrame) -> pd.DataFrame:
    """Detect linear moisture anomalies from NDWI and precipitation residuals.

    High moisture along a narrow corridor relative to surroundings can indicate
    buried water mains (leaks), high-permeability backfill, or natural springs
    following a utility route.

    Adds: moisture_anomaly_score (float [0, 1]).
    """
    df     = df.copy()
    scores = pd.Series(np.zeros(len(df)), index=df.index)
    n_src  = 0

    # Source 1: NDWI from optical
    if 'ndwi' in df.columns:
        ndwi_vals = df['ndwi'].fillna(0.0).values.astype(float)
        ndwi_sc   = np.clip(
            (ndwi_vals - NDWI_WET_THRESH) / (1.0 - NDWI_WET_THRESH), 0.0, 1.0
        )
        scores += ndwi_sc
        n_src  += 1

    # Source 2: CHIRPS precipitation local anomaly
    chirps = (df.get('source_format', pd.Series([''] * len(df))) == 'chirps_precip')
    if chirps.sum() >= MIN_NBHD_PTS:
        c_idx  = df.index[chirps][:3000]
        c_sub  = df.loc[c_idx]
        lat_   = c_sub['lat'].values.astype(float)
        lon_   = c_sub['lon'].values.astype(float)
        prec_  = c_sub['raster_value'].fillna(0.0).values.astype(float)

        z      = _local_zscores(prec_, lat_, lon_, NBHD_RADIUS_DEG)
        pr_sc  = np.clip(z / 3.0, 0.0, 1.0)

        scores.loc[c_idx] += pr_sc
        n_src += 1

    if n_src > 0:
        scores = scores / n_src

    df['moisture_anomaly_score'] = scores.values
    logger.info(
        f"Moisture anomaly: {n_src} source(s), mean={float(scores.mean()):.3f}"
    )
    return df


def fuse_evidence_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Combine SAR + NDVI + moisture into a single infra_evidence_score.

    Adds: infra_evidence_score (float [0, 1]).
    """
    df = df.copy()

    sar   = df.get('sar_linear_score',      pd.Series(np.zeros(len(df)))).fillna(0.0).values
    ndvi  = df.get('ndvi_disturbance_score', pd.Series(np.zeros(len(df)))).fillna(0.0).values
    moist = df.get('moisture_anomaly_score', pd.Series(np.zeros(len(df)))).fillna(0.0).values

    ev = np.clip(
        _W_EVIDENCE['sar']      * sar
        + _W_EVIDENCE['ndvi']   * ndvi
        + _W_EVIDENCE['moisture'] * moist,
        0.0, 1.0,
    )
    df['infra_evidence_score'] = ev
    logger.info(
        f"Evidence score: mean={ev.mean():.3f}, "
        f"confirmed candidate (>0.6)={int((ev > 0.6).sum())}"
    )
    return df


def classify_infrastructure_presence(df: pd.DataFrame) -> pd.DataFrame:
    """Assign infra_status based on evidence score and corridor membership.

    confirmed  — evidence > 0.6 AND on proposed corridor
    suspected  — evidence > 0.6 but off-corridor (unplanned?), OR
                 0.3 < evidence ≤ 0.6 on-corridor
    proposed   — on corridor, evidence ≤ 0.3 (modelled but unverified)
    absent     — off corridor, evidence ≤ 0.3

    Adds: infra_status (str).
    """
    df = df.copy()

    ev     = df.get('infra_evidence_score', pd.Series(np.zeros(len(df)))).fillna(0.0).values
    on_cor = (df.get('infra_corridor', pd.Series(['none'] * len(df))) != 'none').values

    status = np.full(len(df), 'absent', dtype=object)
    for i in range(len(df)):
        e, c = float(ev[i]), bool(on_cor[i])
        if   e > 0.6 and c:        status[i] = 'confirmed'
        elif e > 0.6 and not c:    status[i] = 'suspected'
        elif 0.3 < e <= 0.6:       status[i] = 'suspected'
        elif c:                    status[i] = 'proposed'

    df['infra_status'] = status
    counts = pd.Series(status).value_counts()
    logger.info(f"Infrastructure status:\n{counts.to_string()}")
    return df


def validate_proposed_routes(df: pd.DataFrame) -> pd.DataFrame:
    """Full validation pipeline: SAR → NDVI → moisture → fuse → classify."""
    df = compute_sar_linear_score(df)
    df = compute_ndvi_disturbance_score(df)
    df = compute_moisture_anomaly_score(df)
    df = fuse_evidence_scores(df)
    df = classify_infrastructure_presence(df)
    return df
