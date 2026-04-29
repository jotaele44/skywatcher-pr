import logging

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

logger = logging.getLogger(__name__)

CRS_WGS84 = "EPSG:4326"

ILAP_CLASSIFICATION = "anomaly"
HIGH_CONF_THRESHOLD = 0.75
HYDRO_LINKED_THRESHOLD = 0.50
CLUSTER_NOISE_LABEL = -1


def load_master_dataset(master_path: str) -> gpd.GeoDataFrame:
    """Load final_anomaly_ranked.csv and return as a GeoDataFrame of Points."""
    if not master_path:
        raise FileNotFoundError("master_path is empty.")

    import os
    if not os.path.exists(master_path):
        raise FileNotFoundError(
            f"Master dataset not found at {master_path}. Run the pipeline first."
        )

    df = pd.read_csv(master_path)
    for col in ("lat", "lon"):
        if col not in df.columns:
            raise ValueError(f"Master dataset missing required column: '{col}'")

    geometry = [Point(row.lon, row.lat) for row in df.itertuples(index=False)]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=CRS_WGS84)
    logger.info("Loaded master dataset: %d rows from %s", len(gdf), master_path)
    return gdf


def spatial_filter(
    master_gdf: gpd.GeoDataFrame,
    aoi_gdf: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Return rows from master_gdf whose Point falls within the AOI polygon."""
    if master_gdf.crs != aoi_gdf.crs:
        aoi_gdf = aoi_gdf.to_crs(master_gdf.crs)

    joined = gpd.sjoin(
        master_gdf,
        aoi_gdf[["geometry"]],
        how="inner",
        predicate="within",
    )
    joined = joined.drop(columns=[c for c in joined.columns if c.startswith("index_")], errors="ignore")
    logger.info("Spatial filter: %d / %d points within AOI", len(joined), len(master_gdf))
    return joined


def filter_ilaps(spatial_df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Filter to ILAP candidates (classification == 'anomaly')."""
    if "classification" not in spatial_df.columns:
        logger.warning("'classification' column absent; returning all spatial results as ILAPs.")
        return spatial_df

    ilaps = spatial_df[spatial_df["classification"] == ILAP_CLASSIFICATION].copy()
    logger.info("ILAP filter: %d candidates found", len(ilaps))
    return ilaps


def compute_summary(ilap_gdf: gpd.GeoDataFrame) -> dict:
    """Compute summary statistics from filtered ILAP GeoDataFrame."""
    if ilap_gdf.empty:
        return {
            "total_ilaps": 0,
            "high_confidence_count": 0,
            "hydro_linked_count": 0,
            "corridor_ids": [],
            "corridor_count": 0,
            "mean_confidence": 0.0,
            "mean_physics_score": 0.0,
            "mean_hydro_align": 0.0,
        }

    high_conf = 0
    if "confidence" in ilap_gdf.columns:
        high_conf = int((ilap_gdf["confidence"] > HIGH_CONF_THRESHOLD).sum())

    hydro_linked = 0
    if "hydro_align" in ilap_gdf.columns:
        hydro_linked = int((ilap_gdf["hydro_align"] > HYDRO_LINKED_THRESHOLD).sum())

    corridor_ids: list = []
    if "cluster" in ilap_gdf.columns:
        corridor_ids = sorted(
            int(c) for c in ilap_gdf["cluster"].unique() if c != CLUSTER_NOISE_LABEL
        )

    mean_conf = float(ilap_gdf["confidence"].mean()) if "confidence" in ilap_gdf.columns else 0.0
    mean_phys = float(ilap_gdf["physics_score"].mean()) if "physics_score" in ilap_gdf.columns else 0.0
    mean_hydro = float(ilap_gdf["hydro_align"].mean()) if "hydro_align" in ilap_gdf.columns else 0.0

    return {
        "total_ilaps": len(ilap_gdf),
        "high_confidence_count": high_conf,
        "hydro_linked_count": hydro_linked,
        "corridor_ids": corridor_ids,
        "corridor_count": len(corridor_ids),
        "mean_confidence": mean_conf,
        "mean_physics_score": mean_phys,
        "mean_hydro_align": mean_hydro,
    }


def run_query(
    master_path: str,
    aoi_gdf: gpd.GeoDataFrame,
) -> tuple:
    """Top-level query: load → spatial filter → ILAP filter → summarise."""
    master_gdf = load_master_dataset(master_path)
    spatial_df = spatial_filter(master_gdf, aoi_gdf)
    ilap_gdf = filter_ilaps(spatial_df)
    summary = compute_summary(ilap_gdf)
    return ilap_gdf, summary
