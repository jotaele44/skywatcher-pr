"""
Subsurface Infrastructure Routing Model — Puerto Rico
=======================================================
Uses above-ground terrain + hydrological features to model the optimal
placement of subsurface utilities (water mains, gravity sewers, electrical
conduits, fibre-optic cables).

Key principles
--------------
• Valley / stream corridors → preferred (natural utility rights-of-way,
  gravity-fed systems, easier excavation access)
• Steep slopes → expensive (trench shoring, rock cutting)
• Karst zones → high risk (voids, collapse) → directional boring preferred
• Flood plains → avoid burial → elevated or protected conduit
• PR-specific hub network → Dijkstra least-cost routing between 12 major
  infrastructure centres

Outputs (columns added to the DataFrame)
-----------------------------------------
routing_cost          float [0.01, 1.0]  — per-cell trenching cost
flood_risk            float [0, 1]       — flood susceptibility
infra_corridor        str                — route label or 'none'
corridor_cost         float              — cumulative Dijkstra cost
infra_type            str                — recommended infrastructure type
infra_priority_score  float [0, 1]       — suitability for subsurface infra
"""

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# ── Puerto Rico infrastructure hub network ────────────────────────────────────
PR_HUBS = [
    {'name': 'san_juan',     'lat': 18.466, 'lon': -66.105, 'type': 'metro'},
    {'name': 'bayamon',      'lat': 18.401, 'lon': -66.156, 'type': 'metro'},
    {'name': 'carolina',     'lat': 18.381, 'lon': -65.957, 'type': 'metro'},
    {'name': 'caguas',       'lat': 18.234, 'lon': -65.968, 'type': 'inland'},
    {'name': 'arecibo',      'lat': 18.472, 'lon': -66.716, 'type': 'north_coast'},
    {'name': 'mayaguez',     'lat': 18.201, 'lon': -67.140, 'type': 'west_coast'},
    {'name': 'ponce',        'lat': 17.998, 'lon': -66.614, 'type': 'south_coast'},
    {'name': 'humacao',      'lat': 18.150, 'lon': -65.832, 'type': 'east_coast'},
    {'name': 'aguadilla',    'lat': 18.427, 'lon': -67.154, 'type': 'northwest'},
    {'name': 'guayama',      'lat': 17.984, 'lon': -66.115, 'type': 'south_coast'},
    {'name': 'coamo',        'lat': 18.079, 'lon': -66.360, 'type': 'inland'},
    {'name': 'fajardo',      'lat': 18.326, 'lon': -65.652, 'type': 'east_coast'},
]

# Cost surface weights
_W = {
    'slope':         0.35,
    'elevation':     0.20,
    'karst':         0.25,
    'flood':         0.15,
    'valley_bonus':  0.05,   # subtracted (valleys are preferred)
}

# Dijkstra graph parameters
ROUTING_K_NEIGHBOURS = 12
MAX_ROUTING_POINTS   = 2500   # cap for tractable graph size


def _flood_risk(df: pd.DataFrame) -> np.ndarray:
    """Estimate flood susceptibility [0, 1] from elevation and TWI."""
    elev = df.get('elevation_proxy', pd.Series(np.zeros(len(df)))).fillna(0.0).values.astype(float)
    twi  = df.get('twi',             pd.Series(np.zeros(len(df)))).fillna(0.0).values.astype(float)
    coastal = np.clip(1.0 - np.maximum(elev, 0.0) / 50.0, 0.0, 1.0)
    wet     = np.clip(twi / 15.0, 0.0, 1.0)
    return np.clip(0.60 * coastal + 0.40 * wet, 0.0, 1.0)


def build_routing_cost_surface(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-cell routing_cost and flood_risk.

    Lower cost = preferred corridor for subsurface infrastructure trenching.
    """
    df = df.copy()

    slope = df.get('slope',           pd.Series(np.zeros(len(df)))).fillna(0.0).values.astype(float)
    elev  = df.get('elevation_proxy', pd.Series(np.zeros(len(df)))).fillna(0.0).values.astype(float)
    karst = df.get('karst_penalty',   pd.Series(np.zeros(len(df)))).fillna(0.0).values.astype(float)
    twi   = df.get('twi',             pd.Series(np.zeros(len(df)))).fillna(0.0).values.astype(float)

    # Normalise slope
    s_max = float(slope.max()) or 1.0
    slope_n = np.clip(slope / s_max, 0.0, 1.0)

    # Normalise elevation (above-ground portion only)
    e_above = np.maximum(elev, 0.0)
    e_max   = float(e_above.max()) or 1.0
    elev_n  = np.clip(e_above / e_max, 0.0, 1.0)

    # Valley bonus: high TWI = valley/stream = preferred (reward = cost reduction)
    valley = np.clip(twi / 15.0, 0.0, 1.0)

    flood = _flood_risk(df)
    df['flood_risk'] = flood

    cost = np.clip(
        _W['slope']   * slope_n
        + _W['elevation'] * elev_n
        + _W['karst']     * karst
        + _W['flood']     * flood
        - _W['valley_bonus'] * valley,
        0.01, 1.0,
    )
    df['routing_cost'] = cost

    logger.info(
        f"Routing cost: mean={cost.mean():.3f}, "
        f"min={cost.min():.3f}, max={cost.max():.3f}"
    )
    return df


def compute_least_cost_routes(df: pd.DataFrame) -> pd.DataFrame:
    """Find Dijkstra least-cost paths between PR infrastructure hubs.

    Builds a k-NN sparse graph, runs shortest_path from each hub, traces back
    via predecessors, and labels each point on a path with its corridor name.

    Adds: infra_corridor (str), corridor_cost (float).
    """
    from scipy.spatial import cKDTree
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import shortest_path

    df = df.copy()
    df['infra_corridor'] = 'none'
    df['corridor_cost']  = np.inf

    if 'routing_cost' not in df.columns or len(df) < 20:
        return df

    # Subsample for tractability
    n     = len(df)
    if n > MAX_ROUTING_POINTS:
        rng    = np.random.RandomState(42)
        idx    = rng.choice(n, MAX_ROUTING_POINTS, replace=False)
        sub_df = df.iloc[idx].reset_index(drop=True)
        orig_idx = idx
    else:
        sub_df   = df.reset_index(drop=True)
        orig_idx = np.arange(n)

    ns   = len(sub_df)
    lat  = sub_df['lat'].values.astype(float)
    lon  = sub_df['lon'].values.astype(float)
    cost = sub_df['routing_cost'].values.astype(float)

    pts  = np.column_stack([lat, lon])
    tree = cKDTree(pts)

    # Snap hubs to nearest sub-sample point
    hub_sub_idx = []
    hub_names   = []
    for hub in PR_HUBS:
        _, idx_h = tree.query([[hub['lat'], hub['lon']]], k=1)
        hub_sub_idx.append(int(idx_h[0]))
        hub_names.append(hub['name'])
    # Deduplicate while preserving order
    seen, dedup_hub_idx, dedup_hub_names = set(), [], []
    for i, n_h in zip(hub_sub_idx, hub_names):
        if i not in seen:
            seen.add(i)
            dedup_hub_idx.append(i)
            dedup_hub_names.append(n_h)

    # Build sparse k-NN graph
    k_actual = min(ROUTING_K_NEIGHBOURS + 1, ns)
    _, nn_idx = tree.query(pts, k=k_actual)

    rows, cols, data = [], [], []
    for i in range(ns):
        for j_rel in range(1, k_actual):
            j   = int(nn_idx[i, j_rel])
            w   = float((cost[i] + cost[j]) / 2.0)
            rows.append(i); cols.append(j); data.append(w)

    graph = csr_matrix((data, (rows, cols)), shape=(ns, ns))

    try:
        dist_mat, preds = shortest_path(
            graph, method='D', directed=False,
            indices=dedup_hub_idx, return_predecessors=True,
        )
    except Exception as exc:
        logger.warning(f"Infrastructure routing: Dijkstra failed – {exc}")
        return df

    nh = len(dedup_hub_idx)
    for h1 in range(nh):
        abs1 = dedup_hub_idx[h1]
        for h2 in range(h1 + 1, nh):
            abs2  = dedup_hub_idx[h2]
            d     = float(dist_mat[h1, abs2])
            if not np.isfinite(d):
                continue
            corridor = f"{dedup_hub_names[h1]}_to_{dedup_hub_names[h2]}"

            # Trace path backward from abs2
            path = []
            node = abs2
            pred_row = preds[h1]
            while node != abs1 and node >= 0:
                path.append(node)
                prev = int(pred_row[node])
                if prev < 0 or prev == node:
                    break
                node = prev
            path.append(abs1)

            for sub_node in path:
                orig_row = int(orig_idx[sub_node])
                if df.at[orig_row, 'corridor_cost'] > d:
                    df.at[orig_row, 'infra_corridor'] = corridor
                    df.at[orig_row, 'corridor_cost']  = d

    n_corridor = int((df['infra_corridor'] != 'none').sum())
    logger.info(f"Infrastructure routing: {n_corridor} points on proposed corridors")
    return df


def classify_infrastructure_priority(df: pd.DataFrame) -> pd.DataFrame:
    """Classify the optimal subsurface infrastructure type per cell.

    Rules (priority order):
      karst zone          → directional_bore  (avoid open trench)
      high flood risk     → elevated_electrical (avoid burial)
      stream valley       → gravity_sewer_water_main (gravity-fed ideal)
      low coastal flat    → coastal_water_main
      upland ridge        → electrical_fiber_conduit
      default             → multi_utility

    Adds: infra_type (str), infra_priority_score (float [0, 1]).
    """
    df = df.copy()

    elev  = df.get('elevation_proxy', pd.Series(np.zeros(len(df)))).fillna(0.0).values.astype(float)
    slope = df.get('slope',           pd.Series(np.zeros(len(df)))).fillna(0.0).values.astype(float)
    twi   = df.get('twi',             pd.Series(np.zeros(len(df)))).fillna(0.0).values.astype(float)
    karst = df.get('karst_zone',      pd.Series(np.zeros(len(df), dtype=bool))).fillna(False).values.astype(bool)
    flood = df.get('flood_risk',      pd.Series(np.zeros(len(df)))).fillna(0.0).values.astype(float)

    bathy = df.get('bathymetry_proxy',
                   pd.Series(np.zeros(len(df)))).fillna(0.0).values.astype(float)

    n             = len(df)
    infra_type    = np.full(n, 'multi_utility', dtype=object)
    priority_score = np.full(n, 0.50)

    # Vectorised rule application (later rules overwrite earlier ones)
    upland_ridge       = (elev > 200.0) & (slope < 0.15)
    coastal_flat       = (elev < 20.0)  & (slope < 0.02)
    stream_valley      = (twi  > 8.0)   & (slope < 0.05)
    high_flood         = flood > 0.70
    karst_zone         = karst
    # Offshore: real bathymetry below −200 m marks continental slope / deep sea
    deep_offshore      = bathy < -200.0

    # Deep offshore first — shallower shelf (−200 to −2000 m) scores highest;
    # PR Trench crossings (>−8000 m) score lowest but remain non-zero.
    infra_type[deep_offshore]    = 'submarine_cable'
    priority_score[deep_offshore] = np.clip(
        0.85 - np.abs(bathy[deep_offshore]) / 8400.0, 0.4, 0.85
    )

    infra_type[upland_ridge]  = 'electrical_fiber_conduit'
    priority_score[upland_ridge] = 0.65

    infra_type[coastal_flat]  = 'coastal_water_main'
    priority_score[coastal_flat] = 0.75

    infra_type[stream_valley] = 'gravity_sewer_water_main'
    priority_score[stream_valley] = 0.90

    infra_type[high_flood]    = 'elevated_electrical'
    priority_score[high_flood]   = 0.50

    infra_type[karst_zone]    = 'directional_bore'
    priority_score[karst_zone]   = 0.60

    df['infra_type']           = infra_type
    df['infra_priority_score'] = priority_score

    counts = pd.Series(infra_type).value_counts()
    logger.info(f"Infrastructure type classification:\n{counts.to_string()}")
    return df


def run_infrastructure_model(df: pd.DataFrame) -> pd.DataFrame:
    """Cost surface → Dijkstra routing → infrastructure type classification."""
    df = build_routing_cost_surface(df)
    df = compute_least_cost_routes(df)
    df = classify_infrastructure_priority(df)
    return df
