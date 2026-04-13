import numpy as np
import pandas as pd
import logging
from sklearn.cluster import DBSCAN

logger = logging.getLogger(__name__)


def run_dbscan_clustering(
    df: pd.DataFrame,
    eps_degrees: float = 0.5,
    min_samples: int = 3,
    lat_col: str = 'lat',
    lon_col: str = 'lon',
) -> pd.DataFrame:
    """Run DBSCAN spatial clustering using the haversine metric.

    Coordinates are converted to radians before DBSCAN; eps is expressed
    as degrees and converted to radians accordingly.

    Adds: cluster (integer label; -1 = noise point).
    """
    df = df.copy()

    if len(df) < min_samples:
        logger.warning(
            f"Too few points ({len(df)}) for DBSCAN "
            f"(min_samples={min_samples}) – cluster set to -1"
        )
        df['cluster'] = -1
        return df

    valid_mask = df[[lat_col, lon_col]].notna().all(axis=1)
    if valid_mask.sum() < min_samples:
        logger.warning("Insufficient valid lat/lon rows for DBSCAN – cluster set to -1")
        df['cluster'] = -1
        return df

    coords_deg = df.loc[valid_mask, [lat_col, lon_col]].values.astype(float)
    coords_rad = np.radians(coords_deg)

    eps_rad = eps_degrees * np.pi / 180.0

    dbscan = DBSCAN(
        eps=eps_rad,
        min_samples=min_samples,
        algorithm='ball_tree',
        metric='haversine',
    )
    labels = dbscan.fit_predict(coords_rad)

    df['cluster'] = -1
    df.loc[valid_mask, 'cluster'] = labels

    n_clusters = int(len(set(labels)) - (1 if -1 in labels else 0))
    n_noise    = int((labels == -1).sum())
    logger.info(
        f"DBSCAN (eps={eps_degrees}°, min_samples={min_samples}): "
        f"{n_clusters} clusters, {n_noise} noise points"
    )
    return df


def compute_cluster_statistics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-cluster statistics and merge them back onto the DataFrame.

    Adds (per row):
        cluster_size            – number of points in the cluster
        cluster_lat_centroid    – mean latitude of the cluster
        cluster_lon_centroid    – mean longitude of the cluster
        cluster_avg_physics_score (if physics_score column is present)
    """
    df = df.copy()

    if 'cluster' not in df.columns:
        logger.warning("'cluster' column missing – skipping cluster statistics")
        return df

    agg_dict = {
        'cluster_size':         ('cluster', 'count'),
        'cluster_lat_centroid': ('lat',     'mean'),
        'cluster_lon_centroid': ('lon',     'mean'),
    }

    cluster_stats = df.groupby('cluster').agg(**agg_dict).reset_index()

    if 'physics_score' in df.columns:
        score_stats = (
            df.groupby('cluster')['physics_score']
            .mean()
            .reset_index()
            .rename(columns={'physics_score': 'cluster_avg_physics_score'})
        )
        cluster_stats = cluster_stats.merge(score_stats, on='cluster', how='left')

    df = df.merge(cluster_stats, on='cluster', how='left')
    return df
