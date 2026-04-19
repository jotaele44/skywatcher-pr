"""
Puerto Rico Infrastructure Overlay
====================================
PR-specific infrastructure zones replace the previous generic global zones.
Covers PRASA (water/sewer), PREPA (electrical), fibre backbones, ports,
airports, and critical facility perimeters.

Zones are used both to mask anomalies (expected infrastructure signatures)
and to seed the infrastructure validation layer.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)

# ── Puerto Rico infrastructure zones ─────────────────────────────────────────
#   Each entry: lat_min/max, lon_min/max, name, type
#   types: water, sewer, electrical, fibre, port, airport, industrial, flood_control
INFRASTRUCTURE_ZONES = [
    # ── Metro San Juan water / sewer corridor ──
    {'name': 'sj_metro_water_sewer',
     'lat_min': 18.38, 'lat_max': 18.48, 'lon_min': -66.22, 'lon_max': -65.90,
     'type': 'water_sewer'},

    # ── San Juan–Caguas transmission corridor (PR-52) ──
    {'name': 'sj_caguas_utility_corridor',
     'lat_min': 18.18, 'lat_max': 18.40, 'lon_min': -66.08, 'lon_max': -65.95,
     'type': 'electrical_fibre'},

    # ── PREPA Aguirre Power Complex (south coast) ──
    {'name': 'prepa_aguirre',
     'lat_min': 17.95, 'lat_max': 18.00, 'lon_min': -66.26, 'lon_max': -66.20,
     'type': 'electrical'},

    # ── PREPA AES (Guayama coal plant) ──
    {'name': 'prepa_aes_guayama',
     'lat_min': 17.95, 'lat_max': 18.00, 'lon_min': -66.13, 'lon_max': -66.08,
     'type': 'electrical'},

    # ── PREPA Costa Sur (gas, Guayanilla) ──
    {'name': 'prepa_costa_sur',
     'lat_min': 17.95, 'lat_max': 18.00, 'lon_min': -66.82, 'lon_max': -66.75,
     'type': 'electrical'},

    # ── North coast transmission line (Arecibo–San Juan) ──
    {'name': 'north_coast_transmission',
     'lat_min': 18.40, 'lat_max': 18.50, 'lon_min': -66.75, 'lon_max': -66.10,
     'type': 'electrical'},

    # ── West coast transmission (Mayagüez–Aguadilla) ──
    {'name': 'west_coast_transmission',
     'lat_min': 18.15, 'lat_max': 18.45, 'lon_min': -67.20, 'lon_max': -67.10,
     'type': 'electrical'},

    # ── Río Grande de Arecibo water intake + aqueduct ──
    {'name': 'arecibo_aqueduct',
     'lat_min': 18.28, 'lat_max': 18.48, 'lon_min': -66.80, 'lon_max': -66.68,
     'type': 'water'},

    # ── PR-22 / PR-2 utility corridor (north coast highway) ──
    {'name': 'north_coast_highway_utility',
     'lat_min': 18.40, 'lat_max': 18.50, 'lon_min': -67.20, 'lon_max': -66.10,
     'type': 'fibre_electrical'},

    # ── PR-52 / PR-30 south corridor ──
    {'name': 'south_corridor_utility',
     'lat_min': 17.95, 'lat_max': 18.10, 'lon_min': -66.65, 'lon_max': -65.95,
     'type': 'fibre_electrical'},

    # ── Port of San Juan ──
    {'name': 'port_san_juan',
     'lat_min': 18.45, 'lat_max': 18.48, 'lon_min': -66.12, 'lon_max': -66.06,
     'type': 'port'},

    # ── Port of Ponce ──
    {'name': 'port_ponce',
     'lat_min': 17.96, 'lat_max': 18.00, 'lon_min': -66.66, 'lon_max': -66.58,
     'type': 'port'},

    # ── Luis Muñoz Marín International Airport ──
    {'name': 'lmm_airport',
     'lat_min': 18.42, 'lat_max': 18.45, 'lon_min': -66.02, 'lon_max': -65.98,
     'type': 'airport'},

    # ── Mayagüez wastewater treatment ──
    {'name': 'mayaguez_wwtf',
     'lat_min': 18.18, 'lat_max': 18.23, 'lon_min': -67.17, 'lon_max': -67.12,
     'type': 'sewer'},

    # ── Karst belt subsurface utility (Arecibo–Dorado, directional bore zone) ──
    {'name': 'karst_bore_corridor',
     'lat_min': 18.10, 'lat_max': 18.52, 'lon_min': -67.20, 'lon_max': -66.65,
     'type': 'directional_bore_zone'},

    # ── Submarine cable landing stations ──
    {'name': 'cable_landing_san_juan',
     'lat_min': 18.43, 'lat_max': 18.47, 'lon_min': -66.10, 'lon_max': -66.04,
     'type': 'submarine_cable'},

    {'name': 'cable_landing_mayaguez',
     'lat_min': 18.18, 'lat_max': 18.22, 'lon_min': -67.16, 'lon_max': -67.12,
     'type': 'submarine_cable'},

    # ── Flood control reservoirs ──
    {'name': 'carraizo_reservoir',
     'lat_min': 18.28, 'lat_max': 18.34, 'lon_min': -66.05, 'lon_max': -65.99,
     'type': 'flood_control'},

    {'name': 'la_plata_reservoir',
     'lat_min': 18.32, 'lat_max': 18.38, 'lon_min': -66.17, 'lon_max': -66.11,
     'type': 'flood_control'},

    {'name': 'dos_bocas_reservoir',
     'lat_min': 18.32, 'lat_max': 18.38, 'lon_min': -66.78, 'lon_max': -66.70,
     'type': 'flood_control'},
]


def apply_infrastructure_mask(df: pd.DataFrame) -> pd.DataFrame:
    """Tag each point that falls inside a known PR infrastructure zone.

    Adds:
        infrastructure_zone     — zone name or 'none'
        in_infrastructure_zone  — boolean flag
        infrastructure_type     — zone type string or 'none'
    """
    df = df.copy()
    df['infrastructure_zone']    = 'none'
    df['in_infrastructure_zone'] = False
    df['infrastructure_type']    = 'none'

    if 'lat' not in df.columns or 'lon' not in df.columns:
        logger.warning("lat/lon columns missing – skipping infrastructure mask")
        return df

    lat = df['lat'].values.astype(float)
    lon = df['lon'].values.astype(float)

    for zone in INFRASTRUCTURE_ZONES:
        mask = (
            (lat >= zone['lat_min']) & (lat <= zone['lat_max'])
            & (lon >= zone['lon_min']) & (lon <= zone['lon_max'])
        )
        df.loc[mask, 'infrastructure_zone']    = zone['name']
        df.loc[mask, 'in_infrastructure_zone'] = True
        df.loc[mask, 'infrastructure_type']    = zone['type']

    n_in = int(df['in_infrastructure_zone'].sum())
    logger.info(f"PR infrastructure mask: {n_in}/{len(df)} points in known zones")
    return df


def adjust_classification_for_infrastructure(df: pd.DataFrame) -> pd.DataFrame:
    """Downgrade 'anomaly' labels to 'infrastructure' for known PR infrastructure zones.

    Points in a known zone that were classified as anomalies are reclassified
    as 'infrastructure' — expected signatures should not inflate anomaly scores.
    Exception: infra_status='suspected' (off-model evidence) is left as anomaly
    so it surfaces for human review.
    """
    df = df.copy()

    if 'classification' not in df.columns or 'in_infrastructure_zone' not in df.columns:
        logger.warning("Missing columns for infrastructure reclassification – skipping")
        return df

    # Don't suppress suspected off-model infrastructure
    is_suspected = (
        df.get('infra_status', pd.Series([''] * len(df))) == 'suspected'
    )
    mask = (
        df['in_infrastructure_zone']
        & (df['classification'] == 'anomaly')
        & (~is_suspected)
    )
    n = int(mask.sum())
    df.loc[mask, 'classification'] = 'infrastructure'
    logger.info(f"Reclassified {n} anomaly → infrastructure (PR zone overlap)")
    return df
