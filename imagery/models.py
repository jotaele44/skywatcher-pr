"""
Imagery — data models.

Plain dataclasses shared across providers, the manifest builder, and the MCP
server. Kept dependency-free (no pydantic) so the package imports cheaply and
stays identical across repositories.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SceneMetadata:
    """A single catalog/STAC hit — metadata only, no pixels."""

    provider: str
    scene_id: str
    datetime: Optional[str] = None
    collection: Optional[str] = None
    cloud_cover_pct: Optional[float] = None
    bbox: Optional[list[float]] = None  # (west, south, east, north)
    thumbnail_url: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "scene_id": self.scene_id,
            "datetime": self.datetime,
            "collection": self.collection,
            "cloud_cover_pct": self.cloud_cover_pct,
            "bbox": self.bbox,
            "thumbnail_url": self.thumbnail_url,
            "extra": self.extra,
        }


@dataclass
class ImageryResult:
    """A fetched image plus its provenance metadata."""

    provider: str
    image_bytes: bytes
    media_type: str
    bbox: list[float]  # (west, south, east, north), EPSG:4326
    acquired_at: Optional[str] = None
    collection: Optional[str] = None
    platform: Optional[str] = None
    instrument: Optional[str] = None
    cloud_cover_pct: Optional[float] = None
    resolution_m: Optional[float] = None
    scene_id: Optional[str] = None
    source_uri: Optional[str] = None
    cache_path: Optional[str] = None

    def to_dict(self, include_image: bool = True) -> dict[str, Any]:
        """JSON-safe dict for MCP responses. Image is base64-encoded."""
        d: dict[str, Any] = {
            "provider": self.provider,
            "media_type": self.media_type,
            "bbox": self.bbox,
            "acquired_at": self.acquired_at,
            "collection": self.collection,
            "platform": self.platform,
            "instrument": self.instrument,
            "cloud_cover_pct": self.cloud_cover_pct,
            "resolution_m": self.resolution_m,
            "scene_id": self.scene_id,
            "source_uri": self.source_uri,
            "cache_path": self.cache_path,
            "size_bytes": len(self.image_bytes),
        }
        if include_image:
            d["image_base64"] = base64.b64encode(self.image_bytes).decode("ascii")
        return d


@dataclass
class ChangeResult:
    """Result of comparing two acquisitions of the same footprint."""

    provider: str
    bbox: list[float]
    date1: str
    date2: str
    changed_fraction: float  # 0..1
    changed_pct: float  # 0..100
    threshold: float
    result1: ImageryResult
    result2: ImageryResult

    def to_dict(self, include_images: bool = True) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "bbox": self.bbox,
            "date1": self.date1,
            "date2": self.date2,
            "changed_fraction": self.changed_fraction,
            "changed_pct": self.changed_pct,
            "threshold": self.threshold,
            "image1": self.result1.to_dict(include_image=include_images),
            "image2": self.result2.to_dict(include_image=include_images),
        }
