import json
import logging
import os
from datetime import date

import geopandas as gpd
import requests

logger = logging.getLogger(__name__)

FELT_API_BASE = "https://felt.com/api/v2"

# Columns to include in the published GeoJSON feature properties
_EXPORT_COLS = [
    "lat", "lon", "classification", "confidence",
    "physics_score", "hydro_align", "cluster", "final_score",
]


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def create_map(title: str, lat: float, lon: float, api_key: str) -> tuple:
    """
    Create a new Felt map centred on lat/lon.
    Returns (map_id, map_url).
    """
    resp = requests.post(
        f"{FELT_API_BASE}/maps",
        json={"title": title, "lat": lat, "lon": lon, "zoom": 12},
        headers={**_headers(api_key), "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    map_id = data["id"]
    map_url = data["url"]
    logger.info("Felt map created: %s", map_url)
    return map_id, map_url


def upload_geojson_layer(
    map_id: str,
    geojson_str: str,
    layer_name: str,
    api_key: str,
) -> str:
    """
    Upload a GeoJSON string as a named layer via the Felt presigned S3 flow.

    Steps:
      1. POST /maps/{map_id}/upload → presigned S3 URL + attributes
      2. POST GeoJSON bytes to S3
      3. POST /maps/{map_id}/layers/{layer_id}/finish_upload

    Returns the layer_id.
    """
    # Step 1 — request presigned upload URL
    resp = requests.post(
        f"{FELT_API_BASE}/maps/{map_id}/upload",
        json={"name": layer_name},
        headers={**_headers(api_key), "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    upload_data = resp.json()
    layer_id = upload_data["layer_id"]
    s3_url = upload_data["url"]
    presigned = upload_data.get("presigned_attributes", {})

    # Step 2 — upload to S3 (multipart/form-data)
    fields = {k: (None, v) for k, v in presigned.items()}
    fields["file"] = (f"{layer_name}.geojson", geojson_str.encode(), "application/geo+json")

    s3_resp = requests.post(s3_url, files=fields, timeout=120)
    s3_resp.raise_for_status()
    logger.info("Uploaded GeoJSON layer '%s' to S3 for map %s.", layer_name, map_id)

    # Step 3 — notify Felt the upload is complete
    finish_resp = requests.post(
        f"{FELT_API_BASE}/maps/{map_id}/layers/{layer_id}/finish_upload",
        headers=_headers(api_key),
        timeout=30,
    )
    finish_resp.raise_for_status()
    logger.info("Layer '%s' (id=%s) finalised on Felt map %s.", layer_name, layer_id, map_id)
    return layer_id


def publish_ilaps(
    ilap_gdf: gpd.GeoDataFrame,
    lat: float,
    lon: float,
    aoi_id: str,
    api_key: str,
    title: str = None,
) -> str:
    """
    Publish ILAP results to a new Felt map and return the shareable URL.

    Raises ValueError if ilap_gdf is empty.
    """
    if ilap_gdf is None or ilap_gdf.empty:
        raise ValueError("Cannot publish to Felt: no ILAP results to display.")

    if title is None:
        title = f"PR.INT — ILAP Results {aoi_id} ({date.today()})"

    # Build a clean GeoDataFrame for export (keep only useful columns)
    export_cols = [c for c in _EXPORT_COLS if c in ilap_gdf.columns]
    export_gdf = ilap_gdf[export_cols + ["geometry"]].copy()

    # Ensure geometry is present and valid
    if "geometry" not in export_gdf.columns or export_gdf.geometry.isna().all():
        raise ValueError("ILAP GeoDataFrame has no valid geometry; cannot publish to Felt.")

    if export_gdf.crs is None:
        export_gdf = export_gdf.set_crs("EPSG:4326")
    elif export_gdf.crs.to_epsg() != 4326:
        export_gdf = export_gdf.to_crs("EPSG:4326")

    geojson_str = export_gdf.to_json()

    map_id, map_url = create_map(title, lat, lon, api_key)
    upload_geojson_layer(map_id, geojson_str, f"ILAPs ({aoi_id})", api_key)

    logger.info("ILAP results published to Felt: %s", map_url)
    return map_url
