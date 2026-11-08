"""Curated Sky Cameras catalog (data/reference/sky_cameras) loading, filtering and coverage.

The catalog is hand-curated and checked by tests/test_sky_cameras_catalog.py; this
module only reads it. Liveness written by scripts/check_sky_cameras.py is merged in
at read time, so a camera's ``status`` is the latest check, falling back to the
status recorded when it was curated.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .validation import CATEGORIES, embed_url, normalize_text

CATALOG_FILE = "cameras.v1.json"
CATALOG_SCHEMA = "skywatcher.sky-cameras/v1"
STATUS_FILE = "status.json"
MUNICIPIO_COUNT = 78


@dataclass(frozen=True)
class Camera:
    id: str
    name: str
    categories: tuple[str, ...]
    municipality: str | None
    lat: float | None
    lon: float | None
    provider: str
    page_url: str
    embed: dict[str, str] | None
    terms_note: str
    source_url: str
    verified_at: str
    last_known_status: str
    added_by: str
    contributor: str | None = None
    license: str | None = None
    media_url: str | None = None
    description: str | None = None

    def to_payload(self, status: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = asdict(self)
        payload["categories"] = list(self.categories)
        payload["embed_url"] = embed_url(self.embed)
        payload["status"] = (status or {}).get("status") or self.last_known_status
        payload["checked_at"] = (status or {}).get("checked_at") or self.verified_at
        return payload


def camera_from_dict(row: dict[str, Any]) -> Camera:
    return Camera(
        id=row["id"],
        name=row["name"],
        categories=tuple(row["categories"]),
        municipality=row.get("municipality"),
        lat=row.get("lat"),
        lon=row.get("lon"),
        provider=row["provider"],
        page_url=row["page_url"],
        embed=row.get("embed"),
        terms_note=row.get("terms_note", ""),
        source_url=row.get("source_url", row["page_url"]),
        verified_at=row.get("verified_at", ""),
        last_known_status=row.get("last_known_status", "unknown"),
        added_by=row.get("added_by", "curated"),
        contributor=row.get("contributor"),
        license=row.get("license"),
        media_url=row.get("media_url"),
        description=row.get("description"),
    )


@lru_cache(maxsize=4)
def _load_cached(path: str, mtime_ns: int) -> tuple[Camera, ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != CATALOG_SCHEMA:
        raise ValueError(f"{path}: expected schema {CATALOG_SCHEMA}")
    return tuple(camera_from_dict(row) for row in data["cameras"])


def load_catalog(catalog_dir: Path) -> tuple[Camera, ...]:
    """Load the curated catalog; re-read automatically when the file changes."""
    path = catalog_dir / CATALOG_FILE
    return _load_cached(str(path), path.stat().st_mtime_ns)


def load_status(runtime_root: Path) -> dict[str, dict[str, Any]]:
    """Per-camera liveness from the last scripts/check_sky_cameras.py run, if any."""
    path = runtime_root / STATUS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cameras = data.get("cameras")
    return cameras if isinstance(cameras, dict) else {}


@lru_cache(maxsize=2)
def _municipios_cached(path: str) -> tuple[str, ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(sorted(feature["properties"]["name"] for feature in data["features"]))


def load_municipios(path: Path) -> tuple[str, ...]:
    """The 78 municipality names from the tracked boundaries file."""
    return _municipios_cached(str(path))


def filter_cameras(
    cameras: list[Camera] | tuple[Camera, ...],
    *,
    category: str | None = None,
    municipality: str | None = None,
    q: str | None = None,
) -> list[Camera]:
    """Filter by category, municipality (accent-insensitive) and free text."""
    wanted_municipality = normalize_text(municipality) if municipality else None
    needle = normalize_text(q) if q else None
    out: list[Camera] = []
    for camera in cameras:
        if category and category not in camera.categories:
            continue
        if wanted_municipality and normalize_text(camera.municipality or "") != wanted_municipality:
            continue
        if needle:
            haystack = normalize_text(
                " ".join([camera.name, camera.provider, camera.municipality or "", *camera.categories])
            )
            if needle not in haystack:
                continue
        out.append(camera)
    return out


def coverage_summary(
    cameras: list[Camera] | tuple[Camera, ...],
    municipios: tuple[str, ...],
    statuses: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """How much of Puerto Rico the catalog covers, so gaps are visible, not hidden."""
    statuses = statuses or {}
    by_category = {name: 0 for name in CATEGORIES}
    by_municipality: dict[str, int] = {}
    online = 0
    for camera in cameras:
        for category in camera.categories:
            by_category[category] = by_category.get(category, 0) + 1
        if camera.municipality:
            by_municipality[camera.municipality] = by_municipality.get(camera.municipality, 0) + 1
        status = (statuses.get(camera.id) or {}).get("status") or camera.last_known_status
        online += status == "online"
    covered = sorted(by_municipality)
    return {
        "camera_count": len(cameras),
        "online_count": online,
        "municipio_total": len(municipios) or MUNICIPIO_COUNT,
        "municipios_covered": len(covered),
        "municipios_with_cameras": covered,
        "municipios_without_cameras": [name for name in municipios if name not in by_municipality],
        "by_category": by_category,
        "categories_without_cameras": [name for name, count in by_category.items() if count == 0],
        "by_municipality": dict(sorted(by_municipality.items())),
    }
