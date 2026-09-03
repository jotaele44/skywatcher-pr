"""
Sentinel Hub provider (OAuth2 client credentials).

Implements the Sentinel-Hub-style API shared by both Sentinel Hub and the
Copernicus Data Space Ecosystem (CDSE): an OAuth2 token endpoint, a STAC
Catalog search (``/api/v1/catalog/1.0.0/search``) that carries ``eo:cloud_cover``,
and a Process API (``/api/v1/process``) that renders imagery from an evalscript.

``CopernicusProvider`` subclasses this with CDSE hosts.
"""

from __future__ import annotations

import time
from typing import Any

from .. import config
from ..models import ImageryResult, SceneMetadata
from .base import ImageryProvider, ProviderError, parse_date_range

# Sentinel-2 L2A true-color evalscript (Process API v3).
TRUE_COLOR_EVALSCRIPT = """//VERSION=3
function setup() {
  return { input: ["B02", "B03", "B04"], output: { bands: 3 } };
}
function evaluatePixel(s) {
  return [2.5 * s.B04, 2.5 * s.B03, 2.5 * s.B02];
}
"""


class SentinelHubStyleProvider(ImageryProvider):
    """Shared implementation for Sentinel Hub and CDSE."""

    name = "sentinelhub"
    base_url = config.SENTINELHUB_BASE_URL
    token_url = config.SENTINELHUB_TOKEN_URL
    client_id = config.SENTINELHUB_CLIENT_ID
    client_secret = config.SENTINELHUB_CLIENT_SECRET
    collection = config.SENTINELHUB_COLLECTION

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expiry: float = 0.0

    # ── auth ──────────────────────────────────────────────────────────────────
    def _require_creds(self) -> None:
        if not self.client_id or not self.client_secret:
            raise ProviderError(
                f"{self.name} requires credentials; set the client id/secret env vars"
            )

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 30:
            return self._token
        self._require_creds()
        resp = self._request(
            "POST",
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise ProviderError(
                f"{self.name} token request failed: HTTP {resp.status_code} "
                f"{resp.text[:200]!r}"
            )
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expiry = time.time() + float(payload.get("expires_in", 600))
        return self._token

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}"}

    # ── search ────────────────────────────────────────────────────────────────
    def search(
        self, bbox: list[float], date_range: str, *, max_items: int = 10
    ) -> list[SceneMetadata]:
        start, end = parse_date_range(date_range)
        body = {
            "bbox": list(bbox),
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
            "collections": [self.collection],
            "limit": max_items,
        }
        resp = self._request(
            "POST",
            f"{self.base_url}/api/v1/catalog/1.0.0/search",
            json=body,
            headers={**self._auth_headers(), "Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            raise ProviderError(
                f"{self.name} catalog search failed: HTTP {resp.status_code} "
                f"{resp.text[:200]!r}"
            )
        return [self._parse_feature(f) for f in resp.json().get("features", [])]

    def _parse_feature(self, feature: dict[str, Any]) -> SceneMetadata:
        props = feature.get("properties", {})
        return SceneMetadata(
            provider=self.name,
            scene_id=str(feature.get("id", "")),
            datetime=props.get("datetime"),
            collection=self.collection,
            cloud_cover_pct=props.get("eo:cloud_cover"),
            bbox=feature.get("bbox"),
            extra={"platform": props.get("platform")},
        )

    # ── fetch ─────────────────────────────────────────────────────────────────
    def fetch(
        self, bbox: list[float], date_range: str, *, image_size: int | None = None
    ) -> ImageryResult:
        start, end = parse_date_range(date_range)
        size = image_size or config.DEFAULT_IMAGE_SIZE

        # Best-effort: pick the least-cloudy scene for provenance/cloud cover.
        best: SceneMetadata | None = None
        try:
            scenes = self.search(bbox, date_range, max_items=20)
            scenes = [s for s in scenes if s.cloud_cover_pct is not None]
            if scenes:
                best = min(scenes, key=lambda s: s.cloud_cover_pct)
        except ProviderError:
            best = None

        body = {
            "input": {
                "bounds": {
                    "bbox": list(bbox),
                    "properties": {
                        "crs": "http://www.opengis.net/def/crs/EPSG/0/4326"
                    },
                },
                "data": [
                    {
                        "type": self.collection,
                        "dataFilter": {
                            "timeRange": {
                                "from": f"{start}T00:00:00Z",
                                "to": f"{end}T23:59:59Z",
                            }
                        },
                    }
                ],
            },
            "output": {
                "width": size,
                "height": size,
                "responses": [
                    {"identifier": "default", "format": {"type": "image/png"}}
                ],
            },
            "evalscript": TRUE_COLOR_EVALSCRIPT,
        }
        resp = self._request(
            "POST",
            f"{self.base_url}/api/v1/process",
            json=body,
            headers={
                **self._auth_headers(),
                "Content-Type": "application/json",
                "Accept": "image/png",
            },
        )
        ctype = resp.headers.get("Content-Type", "")
        if resp.status_code != 200 or not ctype.startswith("image/"):
            raise ProviderError(
                f"{self.name} process failed: HTTP {resp.status_code} "
                f"content-type={ctype!r} body={resp.content[:200]!r}"
            )
        return self._cache_and_wrap(
            (self.name, self.collection, start, end, size, *bbox),
            "image/png",
            resp.content,
            bbox=list(bbox),
            acquired_at=(best.datetime if best else end),
            collection=self.collection,
            platform="Sentinel-2",
            instrument="MSI",
            cloud_cover_pct=(best.cloud_cover_pct if best else None),
            resolution_m=10.0,
            scene_id=(best.scene_id if best else None),
            source_uri=f"{self.base_url}/api/v1/process",
        )


class SentinelHubProvider(SentinelHubStyleProvider):
    """Sentinel Hub (services.sentinel-hub.com)."""

    name = "sentinelhub"
    base_url = config.SENTINELHUB_BASE_URL
    token_url = config.SENTINELHUB_TOKEN_URL
    client_id = config.SENTINELHUB_CLIENT_ID
    client_secret = config.SENTINELHUB_CLIENT_SECRET
    collection = config.SENTINELHUB_COLLECTION
