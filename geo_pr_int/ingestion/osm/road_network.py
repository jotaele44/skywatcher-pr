"""
OSM road network ingestion for Puerto Rico via Overpass API.

Provides:
  - Road segment geometries (for dead-end analysis)
  - Dead-end nodes (isolated road termini that may indicate infrastructure access points)
  - Road intersection density (urban inference layer)

Results are cached to data/cache/osm/pr_roads.csv.
"""

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from config import SETTINGS, AOI, GEO_PR_INT_ROOT

logger = logging.getLogger(__name__)

TIMEOUT_S = SETTINGS["osm"].get("timeout_s", 60)
CACHE_FILE = GEO_PR_INT_ROOT / "data" / "cache" / "osm" / "pr_roads.json"
DEAD_END_CACHE = GEO_PR_INT_ROOT / "data" / "cache" / "osm" / "pr_dead_ends.csv"

_OVERPASS_URLS = [SETTINGS["osm"]["overpass_url"]] + SETTINGS["osm"].get("overpass_fallback_urls", [])
_HEADERS = {"User-Agent": "GEO-PR-INT/1.0 (geospatial research; contact: research@example.com)"}


def _overpass_query(query: str, timeout: int = TIMEOUT_S) -> dict:
    """Execute an Overpass QL query, trying each endpoint until one succeeds."""
    for url in _OVERPASS_URLS:
        try:
            resp = requests.post(
                url,
                data={"data": query},
                headers=_HEADERS,
                timeout=timeout + 5,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            logger.warning(f"Overpass timed out ({url})")
        except Exception as exc:
            logger.debug(f"Overpass endpoint failed ({url}): {exc}")
    logger.warning("All Overpass endpoints failed")
    return {}


def _build_dead_end_query(aoi: tuple) -> str:
    min_lon, min_lat, max_lon, max_lat = aoi
    bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    return f"""
[out:json][timeout:{TIMEOUT_S}];
(
  node["highway"="turning_circle"]({bbox});
  node["highway"="turning_loop"]({bbox});
  node["noexit"="yes"]({bbox});
);
out body;
"""


def _build_road_query(aoi: tuple) -> str:
    min_lon, min_lat, max_lon, max_lat = aoi
    bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    return f"""
[out:json][timeout:{TIMEOUT_S}];
(
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified)$"]({bbox});
);
out body;
>;
out skel qt;
"""


def _parse_nodes(data: dict) -> pd.DataFrame:
    """Parse Overpass nodes into a DataFrame."""
    rows = []
    for elem in data.get("elements", []):
        if elem.get("type") == "node":
            rows.append({
                "osm_id":   elem["id"],
                "lat":      elem.get("lat", 0.0),
                "lon":      elem.get("lon", 0.0),
                "highway":  elem.get("tags", {}).get("highway", ""),
                "noexit":   elem.get("tags", {}).get("noexit", ""),
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["osm_id", "lat", "lon", "highway", "noexit"]
    )


def _parse_way_nodes(data: dict) -> dict[int, tuple[float, float]]:
    """Return mapping of node_id → (lat, lon) from an Overpass ways response."""
    nodes = {}
    for elem in data.get("elements", []):
        if elem.get("type") == "node" and "lat" in elem:
            nodes[elem["id"]] = (elem["lat"], elem["lon"])
    return nodes


def _identify_dead_ends_from_ways(data: dict) -> pd.DataFrame:
    """Find nodes that appear only once across all ways (true dead-ends)."""
    node_count: dict[int, int] = {}
    for elem in data.get("elements", []):
        if elem.get("type") == "way":
            for nid in elem.get("nodes", []):
                node_count[nid] = node_count.get(nid, 0) + 1

    # Nodes referenced by only one way segment are road-end candidates
    dead_end_ids = {nid for nid, cnt in node_count.items() if cnt == 1}

    node_coords = _parse_way_nodes(data)
    rows = []
    for nid in dead_end_ids:
        if nid in node_coords:
            lat, lon = node_coords[nid]
            rows.append({"osm_id": nid, "lat": lat, "lon": lon, "dead_end_type": "way_terminus"})

    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["osm_id", "lat", "lon", "dead_end_type"]
    )


def fetch_dead_ends(
    aoi: tuple | None = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Fetch or load dead-end road nodes for the PR AOI.

    Dead-end roads are potential infrastructure access points:
    pump stations, wellheads, treatment plants, etc.

    Returns
    -------
    DataFrame with columns: osm_id, lat, lon, dead_end_type
    """
    if aoi is None:
        aoi = AOI

    DEAD_END_CACHE.parent.mkdir(parents=True, exist_ok=True)

    if use_cache and DEAD_END_CACHE.exists():
        try:
            df = pd.read_csv(DEAD_END_CACHE)
            logger.info(f"OSM dead-ends: loaded {len(df)} from cache")
            return df
        except Exception:
            pass

    logger.info("Querying Overpass API for PR dead-end roads...")

    # First try explicit dead-end node tags
    result = _overpass_query(_build_dead_end_query(aoi))
    df_explicit = _parse_nodes(result)
    if len(df_explicit) > 0:
        df_explicit["dead_end_type"] = "highway_tag"

    # Then find way termini
    result2 = _overpass_query(_build_road_query(aoi))
    df_termini = _identify_dead_ends_from_ways(result2)

    # Combine
    frames = [f for f in [df_explicit, df_termini] if len(f) > 0]
    if not frames:
        logger.warning("No OSM dead-end data returned")
        return pd.DataFrame(columns=["osm_id", "lat", "lon", "dead_end_type"])

    combined = pd.concat(frames, ignore_index=True).drop_duplicates("osm_id")

    # AOI filter
    min_lon, min_lat, max_lon, max_lat = aoi
    combined = combined[
        combined["lon"].between(min_lon, max_lon)
        & combined["lat"].between(min_lat, max_lat)
    ].reset_index(drop=True)

    combined.to_csv(DEAD_END_CACHE, index=False)
    logger.info(f"OSM dead-ends: {len(combined)} nodes fetched and cached")
    return combined


def fetch_road_network(
    aoi: tuple | None = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Fetch PR road network nodes.

    Returns a flat DataFrame of all road nodes (lat, lon, osm_id)
    suitable for spatial joins with ILAP candidates.
    """
    if aoi is None:
        aoi = AOI

    road_cache = GEO_PR_INT_ROOT / "data" / "cache" / "osm" / "pr_road_nodes.csv"
    road_cache.parent.mkdir(parents=True, exist_ok=True)

    if use_cache and road_cache.exists():
        try:
            df = pd.read_csv(road_cache)
            logger.info(f"OSM road nodes: loaded {len(df)} from cache")
            return df
        except Exception:
            pass

    logger.info("Querying Overpass API for PR road network...")
    result = _overpass_query(_build_road_query(aoi))
    node_coords = _parse_way_nodes(result)

    if not node_coords:
        logger.warning("No OSM road data returned")
        return pd.DataFrame(columns=["osm_id", "lat", "lon"])

    rows = [{"osm_id": nid, "lat": lat, "lon": lon} for nid, (lat, lon) in node_coords.items()]
    df = pd.DataFrame(rows)

    min_lon, min_lat, max_lon, max_lat = aoi
    df = df[
        df["lon"].between(min_lon, max_lon)
        & df["lat"].between(min_lat, max_lat)
    ].reset_index(drop=True)

    df.to_csv(road_cache, index=False)
    logger.info(f"OSM road network: {len(df)} nodes cached")
    return df
