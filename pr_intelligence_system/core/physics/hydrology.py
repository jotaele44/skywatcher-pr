"""
Hydrological Analysis — Puerto Rico
=====================================
Replaces synthetic proxies with real D8-based flow analysis on the DEM
point cloud.

Algorithms:
  • D8 flow direction — steepest-descent to nearest-neighbour
  • Flow accumulation — topological sort on the flow DAG
  • TWI (Topographic Wetness Index) — ln(a / tan β)
  • PR karst zone detection (northwest limestone belt)
  • PR river basin assignment (8 major basins)

Retains the original public API (compute_hydrology_alignment,
compute_drainage_index) so the existing pipeline script needs no changes.
"""

import numpy as np
import pandas as pd
import logging
from collections import deque

logger = logging.getLogger(__name__)

# ── Puerto Rico domain constants ──────────────────────────────────────────────
# Northwest karst belt (mogote karst / haystack hills)
PR_KARST_BOUNDS = {
    'lat_min': 18.10, 'lat_max': 18.52,
    'lon_min': -67.20, 'lon_max': -66.65,
}

# Major PR river basin centroids (approximate)
PR_RIVER_BASINS = [
    {'name': 'rio_grande_arecibo', 'lat_c': 18.35, 'lon_c': -66.72},
    {'name': 'rio_la_plata',       'lat_c': 18.37, 'lon_c': -66.15},
    {'name': 'rio_grande_loiza',   'lat_c': 18.30, 'lon_c': -65.75},
    {'name': 'rio_culebrinas',     'lat_c': 18.37, 'lon_c': -67.05},
    {'name': 'rio_guanajibo',      'lat_c': 18.10, 'lon_c': -67.10},
    {'name': 'rio_jacaguas',       'lat_c': 18.03, 'lon_c': -66.58},
    {'name': 'rio_portuguese',     'lat_c': 18.05, 'lon_c': -66.98},
    {'name': 'rio_blanco',         'lat_c': 18.20, 'lon_c': -65.80},
]

# ── Algorithm parameters ──────────────────────────────────────────────────────
K_FLOW_NEIGHBORS      = 8     # D8 neighbourhood size
MIN_DEM_POINTS        = 50    # minimum points before real hydrology is worthwhile
TWI_STREAM_THRESHOLD  = 6.0   # TWI > this → stream / wetland cell
PR_LAT_CENTRE         = 18.20


def _to_metres(lat: np.ndarray, lon: np.ndarray) -> tuple:
    """Equirectangular projection centred on PR (metres)."""
    m_per_deg_lat = 111_000.0
    m_per_deg_lon = 111_000.0 * np.cos(np.radians(PR_LAT_CENTRE))
    y = (lat - PR_LAT_CENTRE) * m_per_deg_lat
    x = (lon - (-66.5))       * m_per_deg_lon
    return x, y


# ── D8 flow direction ─────────────────────────────────────────────────────────

def compute_d8_flow_direction(df: pd.DataFrame) -> pd.DataFrame:
    """Assign each point a D8 flow-direction index (steepest downhill neighbour).

    flow_direction = absolute row index of the receiving cell, or -1 for pits /
    outlets.  Uses the k=8 nearest spatial neighbours.

    Adds: flow_direction (int), is_outlet (bool).
    """
    from scipy.spatial import cKDTree

    df = df.copy()
    n  = len(df)

    if 'elevation_proxy' not in df.columns or n < MIN_DEM_POINTS:
        df['flow_direction'] = -1
        df['is_outlet']      = True
        logger.info("flow_direction: insufficient DEM data – all cells marked as outlets")
        return df

    lat  = df['lat'].values.astype(float)
    lon  = df['lon'].values.astype(float)
    elev = df['elevation_proxy'].fillna(0.0).values.astype(float)

    x, y = _to_metres(lat, lon)
    pts  = np.column_stack([x, y])
    tree = cKDTree(pts)

    k        = min(K_FLOW_NEIGHBORS + 1, n)
    _, nn_idx = tree.query(pts, k=k)

    flow_dir = np.full(n, -1, dtype=np.int64)
    is_outlet = np.ones(n, dtype=bool)

    for i in range(n):
        neighbours = nn_idx[i, 1:]            # exclude self (index 0)
        nb_elevs   = elev[neighbours]
        best       = int(np.argmin(nb_elevs))
        lowest_j   = int(neighbours[best])
        if elev[lowest_j] < elev[i]:
            flow_dir[i] = lowest_j
            is_outlet[i] = False

    df['flow_direction'] = flow_dir
    df['is_outlet']      = is_outlet

    n_routed = int(np.sum(~is_outlet))
    logger.info(f"D8 flow direction: {n_routed}/{n} cells routing, {n - n_routed} outlets")
    return df


# ── Flow accumulation ─────────────────────────────────────────────────────────

def compute_flow_accumulation(df: pd.DataFrame) -> pd.DataFrame:
    """Propagate upstream contributing area via topological sort of the flow DAG.

    Each cell starts with accumulation = 1.  Topological-sort (Kahn's algorithm)
    propagates from headwaters to outlets so no cell is processed before all its
    upstream contributors.

    Adds: flow_accumulation (int ≥ 1).
    """
    df   = df.copy()
    n    = len(df)

    if 'flow_direction' not in df.columns:
        df['flow_accumulation'] = 1
        return df

    flow_dir = df['flow_direction'].values.astype(np.int64)
    accum    = np.ones(n, dtype=float)

    # Build in-degree array
    in_deg = np.zeros(n, dtype=int)
    for i in range(n):
        j = flow_dir[i]
        if 0 <= j < n:
            in_deg[j] += 1

    # Kahn's topological sort
    queue = deque(np.where(in_deg == 0)[0].tolist())
    while queue:
        i = queue.popleft()
        j = int(flow_dir[i])
        if 0 <= j < n:
            accum[j] += accum[i]
            in_deg[j] -= 1
            if in_deg[j] == 0:
                queue.append(j)

    df['flow_accumulation'] = accum.astype(int)
    logger.info(
        f"Flow accumulation: max={int(accum.max())}, "
        f"stream cells (>10 upstream)={int((accum > 10).sum())}"
    )
    return df


# ── Topographic Wetness Index ─────────────────────────────────────────────────

def compute_twi(df: pd.DataFrame) -> pd.DataFrame:
    """Compute TWI = ln( flow_accumulation / tan(slope) ).

    High TWI → valley / wetland → preferred for gravity infrastructure.
    Cells with TWI > TWI_STREAM_THRESHOLD are flagged as stream cells.

    Adds: twi (float), is_stream (bool).
    """
    df = df.copy()

    flow_acc = (
        df['flow_accumulation'].fillna(1.0).values.astype(float)
        if 'flow_accumulation' in df.columns
        else np.ones(len(df))
    )
    slope_rr = (
        df['slope'].fillna(0.0).values.astype(float)
        if 'slope' in df.columns
        else np.zeros(len(df))
    )

    # slope column is rise/run; convert to angle then tan
    tan_slope = np.maximum(np.tan(np.arctan(slope_rr)), 0.001)
    twi       = np.log(np.maximum(flow_acc, 1.0) / tan_slope)
    twi       = np.clip(twi, 0.0, 20.0)

    df['twi']       = twi
    df['is_stream'] = twi > TWI_STREAM_THRESHOLD

    n_stream = int((twi > TWI_STREAM_THRESHOLD).sum())
    logger.info(f"TWI: mean={twi.mean():.2f}, stream cells={n_stream}")
    return df


# ── Karst zone detection ──────────────────────────────────────────────────────

def detect_karst_zones(df: pd.DataFrame) -> pd.DataFrame:
    """Flag the Puerto Rico northwest karst limestone belt.

    The mogote karst terrain (Arecibo–Dorado–Aguadilla arc) has distinct
    subsurface hydrology: water moves through cave systems rather than surface
    streams.  Open trenching is riskier here; directional boring is preferred.

    Adds: karst_zone (bool), karst_penalty (float [0, 1]).
    """
    df  = df.copy()
    lat = df['lat'].values.astype(float)
    lon = df['lon'].values.astype(float)

    karst = (
        (lat >= PR_KARST_BOUNDS['lat_min']) & (lat <= PR_KARST_BOUNDS['lat_max'])
        & (lon >= PR_KARST_BOUNDS['lon_min']) & (lon <= PR_KARST_BOUNDS['lon_max'])
    )

    df['karst_zone']    = karst
    df['karst_penalty'] = np.where(karst, 0.8, 0.0)

    logger.info(f"Karst zones: {int(karst.sum())}/{len(df)} points in NW PR karst belt")
    return df


# ── River basin assignment ────────────────────────────────────────────────────

def assign_river_basin(df: pd.DataFrame) -> pd.DataFrame:
    """Assign each point to the nearest PR major river basin by centroid distance.

    Adds: river_basin (str).
    """
    df   = df.copy()
    lat  = df['lat'].values.astype(float)
    lon  = df['lon'].values.astype(float)

    basin_names = [b['name']  for b in PR_RIVER_BASINS]
    basin_lats  = np.array([b['lat_c'] for b in PR_RIVER_BASINS])
    basin_lons  = np.array([b['lon_c'] for b in PR_RIVER_BASINS])

    assignments = []
    for i in range(len(df)):
        d2   = (basin_lats - lat[i]) ** 2 + (basin_lons - lon[i]) ** 2
        assignments.append(basin_names[int(np.argmin(d2))])

    df['river_basin'] = assignments
    n_basins = len(set(assignments))
    logger.info(f"River basin assignment: {n_basins} basins represented")
    return df


# ── Public API (compatible with existing pipeline) ────────────────────────────

def compute_hydrology_alignment(df: pd.DataFrame) -> pd.DataFrame:
    """Compute hydro_align using real D8/TWI data when available.

    Falls back to the original coastal-proximity + slope proxy when the DEM
    has insufficient points (maintains backward compatibility).

    Adds: hydro_align (float [0, 1]).
    """
    df = df.copy()

    has_real = (
        'twi' in df.columns
        and 'flow_accumulation' in df.columns
        and df['flow_accumulation'].max() > 1
    )

    if has_real:
        twi       = df['twi'].fillna(0.0).values.astype(float)
        flow_acc  = df['flow_accumulation'].fillna(1.0).values.astype(float)
        stream    = df['is_stream'].astype(float).values if 'is_stream' in df.columns else np.zeros(len(df))

        twi_norm  = np.clip(twi / 15.0, 0.0, 1.0)
        acc_norm  = np.log1p(flow_acc) / max(float(np.log1p(flow_acc.max())), 1.0)
        str_score = np.clip(stream * 0.5 + acc_norm * 0.5, 0.0, 1.0)

        hydro_align = np.clip(
            0.40 * twi_norm + 0.30 * acc_norm + 0.30 * str_score, 0.0, 1.0
        )
        logger.info("hydro_align: real D8/TWI hydrology")
    else:
        elev  = (df['elevation_proxy'].fillna(0.0).values.astype(float)
                 if 'elevation_proxy' in df.columns else np.zeros(len(df)))
        slope = (df['slope'].fillna(0.0).values.astype(float)
                 if 'slope' in df.columns else np.zeros(len(df)))

        coast  = 1.0 / (1.0 + np.abs(elev) / 100.0)
        flow_p = np.tanh(slope * 100.0)
        hydro_align = np.clip(coast * 0.6 + flow_p * 0.4, 0.0, 1.0)
        logger.info("hydro_align: synthetic proxy (DEM insufficient)")

    df['hydro_align'] = hydro_align
    logger.info(f"Hydro alignment: mean={hydro_align.mean():.4f}")
    return df


def compute_drainage_index(df: pd.DataFrame) -> pd.DataFrame:
    """Compute drainage_index normalised to [0, 1] from flow accumulation or elevation.

    Adds: drainage_index (float).
    """
    df = df.copy()

    if 'flow_accumulation' in df.columns and df['flow_accumulation'].max() > 1:
        acc   = df['flow_accumulation'].fillna(1.0).values.astype(float)
        max_a = float(acc.max())
        idx   = np.log1p(acc) / np.log1p(max_a)
    elif 'elevation_proxy' in df.columns:
        elev  = df['elevation_proxy'].fillna(0.0).values.astype(float)
        rng   = elev.max() - elev.min()
        idx   = (1.0 - (elev - elev.min()) / rng) if rng > 0 else np.zeros(len(elev))
    else:
        idx   = np.zeros(len(df))

    df['drainage_index'] = idx
    logger.info(f"Drainage index: mean={idx.mean():.4f}")
    return df


# ── Full hydrology pipeline ───────────────────────────────────────────────────

def run_full_hydrology(df: pd.DataFrame) -> pd.DataFrame:
    """Run all hydrological analyses in dependency order."""
    df = compute_d8_flow_direction(df)
    df = compute_flow_accumulation(df)
    df = compute_twi(df)
    df = detect_karst_zones(df)
    df = assign_river_basin(df)
    df = compute_hydrology_alignment(df)
    df = compute_drainage_index(df)
    return df
