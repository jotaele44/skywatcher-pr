"""
Imagery providers — base interface.

Defines the provider contract and shared HTTP/parsing helpers. Concrete
providers implement ``fetch`` (pull an image for a footprint + date range) and
``search`` (catalog/STAC lookup returning metadata only).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

import requests

from .. import cache, config, geo
from ..models import ImageryResult, SceneMetadata


class ProviderError(Exception):
    """Raised for provider misconfiguration or non-recoverable fetch failure."""


def parse_date_range(date_range: str) -> tuple[str, str]:
    """Parse ``"start/end"`` (or a single date) into ``(start, end)`` ISO dates.

    Accepts ``"2024-01-01/2024-01-31"`` or a bare ``"2024-01-01"`` (start==end).
    """
    if not date_range:
        raise ProviderError("date_range is required (e.g. '2024-01-01/2024-01-31')")
    parts = [p.strip() for p in date_range.split("/") if p.strip()]
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], parts[1]


class ImageryProvider(ABC):
    """Common HTTP plumbing + the fetch/search contract."""

    name: str = "base"

    def _session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({"User-Agent": config.USER_AGENT})
        return s

    def _request(
        self,
        method: str,
        url: str,
        *,
        session: requests.Session | None = None,
        **kwargs,
    ) -> requests.Response:
        """HTTP request with retry/backoff, mirroring earthgpt/tiles.py."""
        sess = session or self._session()
        kwargs.setdefault("timeout", config.FETCH_TIMEOUT_S)
        last_exc: Exception | None = None
        for attempt in range(config.FETCH_RETRIES):
            try:
                resp = sess.request(method, url, **kwargs)
                if resp.status_code < 500 and resp.status_code != 429:
                    return resp
                last_exc = ProviderError(f"HTTP {resp.status_code} from {url}")
            except requests.RequestException as exc:
                last_exc = exc
            if attempt < config.FETCH_RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))
        raise ProviderError(f"request to {url} failed: {last_exc}")

    def _cache_and_wrap(
        self, key_parts: tuple, media_type: str, data: bytes, **result_kwargs
    ) -> ImageryResult:
        key = cache.cache_key(*key_parts)
        path = cache.write(key, media_type, data)
        return ImageryResult(
            provider=self.name,
            image_bytes=data,
            media_type=media_type,
            cache_path=str(path),
            **result_kwargs,
        )

    # ── contract ────────────────────────────────────────────────────────────
    @abstractmethod
    def fetch(
        self, bbox: list[float], date_range: str, *, image_size: int | None = None
    ) -> ImageryResult:
        """Fetch a rendered image for ``bbox`` over ``date_range``."""

    @abstractmethod
    def search(
        self, bbox: list[float], date_range: str, *, max_items: int = 10
    ) -> list[SceneMetadata]:
        """Catalog/STAC search returning metadata only (no pixels)."""

    # ── shared convenience ────────────────────────────────────────────────────
    def fetch_point(
        self,
        lat: float,
        lon: float,
        date_range: str,
        *,
        buffer_deg: float | None = None,
        image_size: int | None = None,
    ) -> ImageryResult:
        bbox = geo.bbox_from_point(lat, lon, buffer_deg)
        return self.fetch(bbox, date_range, image_size=image_size)
