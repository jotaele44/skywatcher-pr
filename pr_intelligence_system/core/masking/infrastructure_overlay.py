import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Known infrastructure bounding boxes:  (lat_min, lat_max, lon_min, lon_max)
INFRASTRUCTURE_ZONES = [
    {
        'name':    'port_zone_gulf_mexico',
        'lat_min': 25.0,  'lat_max': 35.0,
        'lon_min': -97.0, 'lon_max': -80.0,
        'type':    'port',
    },
    {
        'name':    'shipping_lane_atlantic',
        'lat_min': 0.0,   'lat_max': 10.0,
        'lon_min': -20.0, 'lon_max': 20.0,
        'type':    'shipping',
    },
    {
        'name':    'industrial_zone_western_europe',
        'lat_min': 40.0,  'lat_max': 55.0,
        'lon_min': -5.0,  'lon_max': 20.0,
        'type':    'industrial',
    },
    {
        'name':    'port_zone_east_asia',
        'lat_min': 20.0,  'lat_max': 40.0,
        'lon_min': 110.0, 'lon_max': 130.0,
        'type':    'port',
    },
    {
        'name':    'shipping_lane_indian_ocean',
        'lat_min': -10.0, 'lat_max': 10.0,
        'lon_min': 50.0,  'lon_max': 90.0,
        'type':    'shipping',
    },
]


def apply_infrastructure_mask(df: pd.DataFrame) -> pd.DataFrame:
    """Tag each point that falls inside a known infrastructure zone.

    Adds:
        infrastructure_zone     – zone name or 'none'
        in_infrastructure_zone  – boolean flag
    """
    df = df.copy()
    df['infrastructure_zone']    = 'none'
    df['in_infrastructure_zone'] = False

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

    n_infra = int(df['in_infrastructure_zone'].sum())
    logger.info(f"Infrastructure mask: {n_infra} of {len(df)} points in known zones")
    return df


def adjust_classification_for_infrastructure(df: pd.DataFrame) -> pd.DataFrame:
    """Downgrade 'anomaly' labels to 'infrastructure' for known infrastructure zones.

    Points that were classified as anomalies but fall inside a known
    infrastructure zone are reclassified as 'infrastructure'.
    """
    df = df.copy()

    if 'classification' not in df.columns or 'in_infrastructure_zone' not in df.columns:
        logger.warning(
            "Cannot adjust classification: missing 'classification' or "
            "'in_infrastructure_zone' column"
        )
        return df

    mask = df['in_infrastructure_zone'] & (df['classification'] == 'anomaly')
    n_reclassified = int(mask.sum())
    df.loc[mask, 'classification'] = 'infrastructure'

    logger.info(
        f"Reclassified {n_reclassified} anomaly → infrastructure "
        "due to infrastructure zone overlap"
    )
    return df
