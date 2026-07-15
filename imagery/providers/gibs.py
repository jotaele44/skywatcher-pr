"""
NASA GIBS provider (no authentication).

Fetches imagery via the GIBS WMS GetMap endpoint (EPSG:4326). GIBS serves daily
global composites, so there is no per-scene cloud-cover metadata — ``search``
returns one synthetic daily-mosaic descriptor per day in the range and
``cloud_cover_pct`` is ``None`` on fetched results.

Docs: https://nasa-gibs.github.io/gibs-api-docs/
"""

from __future__ import annotations

from datetime import date, timedelta

from .. import config
from ..models import ImageryResult, SceneMetadata
from .base import ImageryProvider, ProviderError, parse_date_range


def _daterange_days(start: str, end: str, cap: int = 31) -> list[str]:
    try:
        d0 = date.fromisoformat(start)
        d1 = date.fromisoformat(end)
    except ValueError as exc:
        raise ProviderError(f"invalid date in range: {exc}") from exc
    if d1 < d0:
        d0, d1 = d1, d0
    out = []
    cur = d0
    while cur <= d1 and len(out) < cap:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


class GibsProvider(ImageryProvider):
    name = "gibs"

    def fetch(
        self, bbox: list[float], date_range: str, *, image_size: int | None = None
    ) -> ImageryResult:
        start, end = parse_date_range(date_range)
        # GIBS composites are per-day; use the range end (most recent) day.
        day = _daterange_days(start, end)[-1]
        size = image_size or config.DEFAULT_IMAGE_SIZE
        west, south, east, north = bbox[:4]

        params = {
            "SERVICE": "WMS",
            "VERSION": "1.3.0",
            "REQUEST": "GetMap",
            "LAYERS": config.GIBS_DEFAULT_LAYER,
            "CRS": "EPSG:4326",
            # WMS 1.3.0 EPSG:4326 axis order is lat,lon → south,west,north,east.
            "BBOX": f"{south},{west},{north},{east}",
            "WIDTH": str(size),
            "HEIGHT": str(size),
            "FORMAT": "image/jpeg",
            "TIME": day,
        }
        resp = self._request("GET", config.GIBS_WMS_URL, params=params)
        ctype = resp.headers.get("Content-Type", "")
        if resp.status_code != 200 or not ctype.startswith("image/"):
            raise ProviderError(
                f"GIBS GetMap failed: HTTP {resp.status_code} content-type={ctype!r} "
                f"body={resp.content[:200]!r}"
            )
        return self._cache_and_wrap(
            (self.name, config.GIBS_DEFAULT_LAYER, day, size, *bbox),
            "image/jpeg",
            resp.content,
            bbox=list(bbox),
            acquired_at=day,
            collection=config.GIBS_DEFAULT_LAYER,
            platform="Terra",
            instrument="MODIS",
            cloud_cover_pct=None,
            scene_id=f"gibs:{config.GIBS_DEFAULT_LAYER}:{day}",
            source_uri=f"{config.GIBS_WMS_URL}?TIME={day}&LAYERS={config.GIBS_DEFAULT_LAYER}",
        )

    def search(
        self, bbox: list[float], date_range: str, *, max_items: int = 10
    ) -> list[SceneMetadata]:
        start, end = parse_date_range(date_range)
        days = _daterange_days(start, end, cap=max_items)
        return [
            SceneMetadata(
                provider=self.name,
                scene_id=f"gibs:{config.GIBS_DEFAULT_LAYER}:{day}",
                datetime=day,
                collection=config.GIBS_DEFAULT_LAYER,
                cloud_cover_pct=None,
                bbox=list(bbox),
                extra={"note": "GIBS daily global composite (no per-scene cloud cover)"},
            )
            for day in days
        ]
