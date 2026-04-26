"""
PostGIS writer for GEO-PR-INT.

Writes candidates, corridors, and contracts to PostGIS tables.
All operations are wrapped in try/except — the system works without PostGIS.
"""

import logging

import pandas as pd

from storage.postgis.schema import (
    CANDIDATES_TABLE,
    CORRIDORS_TABLE,
    CONTRACTS_TABLE,
    create_tables,
    postgis_available,
)

logger = logging.getLogger(__name__)


def _df_to_geodataframe(df: pd.DataFrame, lat_col: str = "lat", lon_col: str = "lon"):
    """Convert DataFrame to GeoDataFrame with Point geometry in EPSG:4326."""
    import geopandas as gpd
    from shapely.geometry import Point

    df = df.copy()
    geom = [
        Point(row[lon_col], row[lat_col])
        if pd.notna(row.get(lon_col)) and pd.notna(row.get(lat_col))
        else None
        for _, row in df.iterrows()
    ]
    gdf = gpd.GeoDataFrame(df, geometry=geom, crs="EPSG:4326")
    return gdf


def write_candidates(
    df: pd.DataFrame,
    engine,
    if_exists: str = "replace",
) -> int:
    """Write ILAP candidates to PostGIS. Returns rows written, 0 on failure."""
    if df.empty:
        logger.info("No candidates to write to PostGIS")
        return 0
    try:
        gdf = _df_to_geodataframe(df)
        gdf.to_postgis(CANDIDATES_TABLE, engine, if_exists=if_exists, index=False)
        n = len(gdf)
        logger.info(f"PostGIS: wrote {n} candidates to {CANDIDATES_TABLE}")
        return n
    except ImportError:
        logger.warning("geopandas not installed — skipping PostGIS write for candidates")
        return 0
    except Exception as exc:
        logger.error(f"PostGIS write failed for candidates: {exc}")
        return 0


def write_corridors(
    corridors_df: pd.DataFrame,
    engine,
    if_exists: str = "replace",
) -> int:
    """Write corridor records to PostGIS. Returns rows written, 0 on failure."""
    if corridors_df.empty:
        logger.info("No corridors to write to PostGIS")
        return 0
    try:
        lat_col = "centroid_lat" if "centroid_lat" in corridors_df.columns else "lat"
        lon_col = "centroid_lon" if "centroid_lon" in corridors_df.columns else "lon"
        if lat_col not in corridors_df.columns:
            logger.warning("Corridors DataFrame has no centroid coords — skipping PostGIS write")
            return 0
        gdf = _df_to_geodataframe(corridors_df, lat_col=lat_col, lon_col=lon_col)
        gdf.to_postgis(CORRIDORS_TABLE, engine, if_exists=if_exists, index=False)
        n = len(gdf)
        logger.info(f"PostGIS: wrote {n} corridors to {CORRIDORS_TABLE}")
        return n
    except ImportError:
        logger.warning("geopandas not installed — skipping PostGIS write for corridors")
        return 0
    except Exception as exc:
        logger.error(f"PostGIS write failed for corridors: {exc}")
        return 0


def write_contracts(
    contracts_df: pd.DataFrame,
    engine,
    if_exists: str = "replace",
) -> int:
    """Write contracts to PostGIS. Returns rows written, 0 on failure."""
    if contracts_df.empty:
        logger.info("No contracts to write to PostGIS")
        return 0
    try:
        df = contracts_df.copy()
        # matched_keywords may be a list — serialise to string
        if "matched_keywords" in df.columns:
            df["matched_keywords"] = df["matched_keywords"].apply(
                lambda v: ",".join(v) if isinstance(v, list) else str(v or "")
            )
        gdf = _df_to_geodataframe(df)
        gdf.to_postgis(CONTRACTS_TABLE, engine, if_exists=if_exists, index=False)
        n = len(gdf)
        logger.info(f"PostGIS: wrote {n} contracts to {CONTRACTS_TABLE}")
        return n
    except ImportError:
        logger.warning("geopandas not installed — skipping PostGIS write for contracts")
        return 0
    except Exception as exc:
        logger.error(f"PostGIS write failed for contracts: {exc}")
        return 0


def write_all(
    candidates_df: pd.DataFrame,
    corridors_df: pd.DataFrame,
    contracts_df: pd.DataFrame,
    engine,
    if_exists: str = "replace",
) -> dict:
    """
    Write all three tables to PostGIS.

    Returns dict with row counts: {candidates, corridors, contracts}.
    If PostGIS is unavailable, returns zeros without raising.
    """
    if not postgis_available(engine):
        logger.warning("PostGIS not available — skipping all DB writes")
        return {"candidates": 0, "corridors": 0, "contracts": 0}

    try:
        create_tables(engine)
    except Exception as exc:
        logger.warning(f"Table creation failed: {exc}")

    return {
        "candidates": write_candidates(candidates_df, engine, if_exists=if_exists),
        "corridors":  write_corridors(corridors_df, engine, if_exists=if_exists),
        "contracts":  write_contracts(contracts_df, engine, if_exists=if_exists),
    }
