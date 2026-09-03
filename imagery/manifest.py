"""
Imagery — manifest builder.

Maps an :class:`ImageryResult` onto a ``satellite_source_manifest`` document so
fetched tiles flow through the repository's existing satellite-ingest pipeline
(schemas/satellite_source_manifest.schema.json). This is the integration point
that keeps imagery inside the same retrieval pipeline as other spatial records.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from . import geo
from .models import ImageryResult

SCHEMA_VERSION = "1.0"
PRODUCER = "imagery-mcp"
PROCESSING_PIPELINE = "imagery.fetch_imagery"

# Per-provider default acquisition license + reliability.
_PROVIDER_META = {
    "gibs": {
        "license": "NASA EOSDIS (public domain)",
        "reliability": "medium",
        "platform": "Terra",
        "instrument": "MODIS",
        "collection": "MODIS_Terra_CorrectedReflectance_TrueColor",
    },
    "sentinelhub": {
        "license": "Copernicus Sentinel data (ESA)",
        "reliability": "high",
        "platform": "Sentinel-2",
        "instrument": "MSI",
        "collection": "sentinel-2-l2a",
    },
    "copernicus": {
        "license": "Copernicus Sentinel data (CDSE)",
        "reliability": "high",
        "platform": "Sentinel-2",
        "instrument": "MSI",
        "collection": "sentinel-2-l2a",
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _footprint(bbox: list[float]) -> dict[str, Any]:
    west, south, east, north = bbox[:4]
    ring = [
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def build_manifest(result: ImageryResult, synthetic: bool = False) -> dict[str, Any]:
    """Build a schema-shaped satellite_source_manifest dict from a fetch result.

    The footprint is clamped to the Puerto Rico envelope so the document stays
    within the schema's coordinate constraints. ``synthetic`` marks
    fixture/test-derived results so they bypass the non-synthetic URI guard.
    """
    pmeta = _PROVIDER_META.get(result.provider, {})
    bbox = geo.clamp_bbox_to_pr(result.bbox)
    checksum = hashlib.sha256(result.image_bytes).hexdigest()
    acquired = result.acquired_at or _now_iso()

    cloud = result.cloud_cover_pct
    if cloud is None:
        cloud = 0.0
        reliability = "unverified"
    else:
        reliability = pmeta.get("reliability", "medium")

    asset: dict[str, Any] = {
        "checksum_sha256": checksum,
        "media_type": result.media_type,
    }
    if result.cache_path:
        asset["local_path"] = result.cache_path
    if result.source_uri:
        asset["source_uri"] = result.source_uri
    if "local_path" not in asset and "source_uri" not in asset:
        # Schema requires at least one asset locator.
        asset["source_uri"] = f"imagery://{result.provider}/{checksum}"

    manifest: dict[str, Any] = {
        "manifest_id": f"imagery-{result.provider}-{uuid.uuid4().hex[:12]}",
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "created_at": _now_iso(),
        "synthetic": synthetic,
        "source": {
            "provider": result.provider,
            "collection": result.collection or pmeta.get("collection", "unknown"),
            "platform": result.platform or pmeta.get("platform", "unknown"),
            "instrument": result.instrument or pmeta.get("instrument", "unknown"),
        },
        "acquisition": {
            "acquired_at": acquired,
            "processed_at": _now_iso(),
            "license": pmeta.get("license", "unspecified"),
        },
        "asset": asset,
        "geometry": {
            "crs": "EPSG:4326",
            "footprint": _footprint(bbox),
            "bbox": bbox,
        },
        "puerto_rico": {"region": "full_island"},
        "quality": {
            "cloud_cover_pct": float(cloud),
            "geometric_confidence": 0.6,
            "source_reliability": reliability,
        },
        "lineage": {
            "processing_pipeline": PROCESSING_PIPELINE,
            "pipeline_version": SCHEMA_VERSION,
            "derived_from": [result.scene_id] if result.scene_id else [],
        },
    }
    if result.resolution_m:
        manifest["quality"]["resolution_m"] = float(result.resolution_m)
    return manifest
