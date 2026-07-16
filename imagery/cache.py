"""
Imagery — local content cache.

Content-addressed cache for fetched imagery under ``config.CACHE_DIR``. A cache
key is derived from the request parameters (provider, bbox, date, layer, size)
and hashed to a stable filename. Mirrors the fetch/cache discipline in
``earthgpt/tiles.py`` (validate on read, re-fetch on corruption).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import config

_EXT_BY_MEDIA = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/tiff": ".tiff",
}


def cache_key(*parts: object) -> str:
    """Stable hash of the request parameters."""
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def cache_path(key: str, media_type: str) -> Path:
    ext = _EXT_BY_MEDIA.get(media_type.lower(), ".img")
    return config.CACHE_DIR / f"{key}{ext}"


def read(key: str, media_type: str) -> bytes | None:
    """Return cached bytes for ``key`` if present and non-trivial, else None."""
    p = cache_path(key, media_type)
    if p.exists() and p.stat().st_size >= 100:
        return p.read_bytes()
    return None


def write(key: str, media_type: str, data: bytes) -> Path:
    """Persist ``data`` under ``key`` and return the path written."""
    p = cache_path(key, media_type)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p
