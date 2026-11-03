"""Live public-feed endpoints for the /live airspace map.

These endpoints proxy the keyless adsb.lol community aggregator (ODbL-1.0
data) and the key-gated openAIP tile service for the browser. The browser
cannot call those services directly: api.adsb.lol sends no CORS headers, the
replay chunks are ~15 MB each and are cut down here to the viewport, and the
openAIP key must not ship in the frontend bundle.

Upstream failures are reported in-band (``status`` plus ``reason``) with HTTP
200, because the backend itself is healthy; the GUI renders them as offline or
stale states. Malformed requests are HTTP 422. Nothing here is persisted:
``scripts/adsb_poll.py --provider adsblol`` is the persistence path.
"""

from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response

from adsb import config as adsb_config
from adsb.heatmap import HeatmapFormatError, chunk_index, decode_heatmap
from adsb.providers.adsblol import (
    ATTRIBUTION,
    LICENSE,
    AdsbLolProvider,
    UpstreamNotFound,
    normalize_hex,
)
from adsb.providers.base import ProviderError

from .query import QueryValidationError, parse_bbox
from .time import UTCValidationError, parse_utc_datetime

router = APIRouter(prefix="/api/console/live", tags=["console-live"])
logger = logging.getLogger(__name__)

# Clients get fixed, user-safe reasons; the exception detail (upstream URLs,
# network errors) is logged server-side only.
UPSTREAM_REASON = "adsb.lol could not be reached or returned an error; details are in the backend log."
NOT_FOUND_REASONS = {
    "adsblol.aircraft": "adsb.lol returned no data for this request.",
    "adsblol.military": "adsb.lol returned no data for this request.",
    "adsblol.trace": "adsb.lol has no trace for this aircraft on this day.",
    "adsblol.replay": "adsb.lol has no replay data for this time.",
    "adsblol.routes": "adsb.lol returned no route data.",
}
DECODE_REASON = "The adsb.lol replay chunk could not be decoded."

OPENAIP_TILE_URL = os.getenv(
    "OPENAIP_TILE_URL", "https://api.tiles.openaip.net/api/data/openaip/{z}/{x}/{y}.png"
)
REPLAY_FIELDS = ["hex", "lat", "lon", "alt_baro", "gs", "source_type", "flight", "squawk"]
_PROVIDER: AdsbLolProvider | None = None


def get_live_provider() -> AdsbLolProvider:
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = AdsbLolProvider()
    return _PROVIDER


LiveProvider = Annotated[AdsbLolProvider, Depends(get_live_provider)]


def _openaip_key() -> str:
    return os.getenv("OPENAIP_API_KEY", "").strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _source(feed: str, url: str | None = None) -> dict[str, Any]:
    return {
        "provider": "adsb.lol",
        "feed": feed,
        "upstream_url": url,
        "license": LICENSE,
        "attribution": ATTRIBUTION,
        "source_family": "operational_position",
        "source_method": "public_aggregator_api",
        "persisted": False,
    }


def _unavailable(feed: str, exc: Exception, **extra: Any) -> dict[str, Any]:
    logger.warning("live feed %s unavailable: %s", feed, exc)
    if isinstance(exc, UpstreamNotFound):
        reason = NOT_FOUND_REASONS.get(feed, UPSTREAM_REASON)
    elif isinstance(exc, HeatmapFormatError):
        reason = DECODE_REASON
    else:
        reason = UPSTREAM_REASON
    return {
        "feed": feed,
        "status": "upstream_unavailable",
        "reason": reason,
        "fetched_at_utc": _now_iso(),
        "source": _source(feed),
        **extra,
    }


def _bbox(value: str) -> list[float]:
    try:
        parsed = parse_bbox(value)
    except QueryValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if parsed is None:
        raise HTTPException(status_code=422, detail="bbox is required (west,south,east,north)")
    return list(parsed)


@router.get("/status")
def live_status() -> dict[str, Any]:
    """Configuration-only status of every backend-mediated live feed."""

    openaip_ready = bool(_openaip_key())
    return {
        "generated_at_utc": _now_iso(),
        "network_required": True,
        "feeds": [
            {"id": "adsblol.aircraft", "label": "Live aircraft (adsb.lol /v2/point)", "status": "configured", "endpoint": "/api/console/live/aircraft"},
            {"id": "adsblol.military", "label": "Military aircraft (adsb.lol /v2/mil)", "status": "configured", "endpoint": "/api/console/live/aircraft?military=true"},
            {"id": "adsblol.trace", "label": "Aircraft traces (adsb.lol traces / globe_history)", "status": "configured", "endpoint": "/api/console/live/trace/{hex}"},
            {"id": "adsblol.replay", "label": "Replay (adsb.lol globe_history heatmap chunks)", "status": "configured", "endpoint": "/api/console/live/replay"},
            {"id": "adsblol.routes", "label": "Flight routes (adsb.lol routeset)", "status": "configured", "endpoint": "/api/console/live/routes"},
            {
                "id": "openaip.tiles",
                "label": "openAIP aeronautical tiles",
                "status": "configured" if openaip_ready else "missing_credentials",
                "reason": None if openaip_ready else "Set OPENAIP_API_KEY (free key from openaip.net) on the backend.",
                "endpoint": "/api/console/live/tiles/openaip/{z}/{x}/{y}.png",
            },
        ],
        "adsblol": {
            "api_base": adsb_config.ADSBLOL_API_BASE,
            "site_base": adsb_config.ADSBLOL_SITE_BASE,
            "max_radius_nm": adsb_config.ADSBLOL_MAX_RADIUS_NM,
            "license": LICENSE,
            "attribution": ATTRIBUTION,
        },
        "openaip": {"configured": openaip_ready},
        "policy": {
            "persisted": False,
            "bot_protected_endpoints_used": False,
            "fr24_scraping": False,
            "upstream_errors_in_band": True,
        },
    }


@router.get("/aircraft")
def live_aircraft(
    provider: LiveProvider,
    bbox: str = Query(..., description="west,south,east,north"),
    military: bool = Query(False, description="Only military aircraft (adsb.lol /v2/mil)"),
    hex: str | None = Query(None, description="Comma-separated ICAO addresses to include even outside the view"),
) -> dict[str, Any]:
    box = _bbox(bbox)
    hexes = [part for part in (hex or "").split(",") if part.strip()]
    feed = "adsblol.military" if military else "adsblol.aircraft"
    try:
        hexes = [normalize_hex(part) for part in hexes]
    except ProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        result = provider.fetch_aircraft(box, military=military, hexes=hexes)
    except ProviderError as exc:
        return _unavailable(feed, exc, aircraft=[], bbox=box)
    return {
        "feed": feed,
        "status": "available",
        "reason": None if result["coverage"].get("complete", True) else (
            "View is wider than the 250 NM upstream query radius; aircraft near the edges may be missing."
        ),
        "fetched_at_utc": _now_iso(),
        "upstream_now_ms": result.get("now"),
        "bbox": box,
        "coverage": result["coverage"],
        "count": len(result["aircraft"]),
        "aircraft": result["aircraft"],
        "source": _source(feed, result.get("upstream_url")),
    }


@router.get("/trace/{hex_id}")
def live_trace(
    provider: LiveProvider,
    hex_id: str,
    day: str | None = Query(None, alias="date", description="UTC day YYYY-MM-DD; omit for today"),
) -> dict[str, Any]:
    try:
        hex_id = normalize_hex(hex_id)
        parsed_day = date.fromisoformat(day) if day else None
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        trace = provider.fetch_trace(hex_id, parsed_day)
    except ProviderError as exc:
        return _unavailable("adsblol.trace", exc, hex=hex_id, points=[])
    return {
        "feed": "adsblol.trace",
        "status": "available" if trace["points"] else "empty",
        "reason": None if trace["points"] else "Upstream trace file has no positions for this aircraft and day.",
        "fetched_at_utc": _now_iso(),
        **{key: value for key, value in trace.items() if key != "upstream_url"},
        "source": _source("adsblol.trace", trace.get("upstream_url")),
    }


@router.get("/replay")
def live_replay(
    provider: LiveProvider,
    ts: str = Query(..., description="ISO-8601 UTC timestamp to replay from"),
    bbox: str = Query(..., description="west,south,east,north"),
    window_s: int = Query(300, ge=10, le=1800, description="Seconds of frames to return from ts"),
) -> dict[str, Any]:
    box = _bbox(bbox)
    try:
        requested = parse_utc_datetime(ts, field_name="ts")
    except UTCValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    latest_start = provider.latest_complete_chunk_start()
    latest_end = latest_start + timedelta(minutes=30)
    moment = requested
    clamped = False
    if requested >= latest_end:
        # Same rule as the adsb.lol map: the half hour in progress is not yet
        # published, so jump to one minute into the newest complete chunk.
        moment = latest_start + timedelta(minutes=1)
        clamped = True
    chunk_start = moment.replace(minute=(moment.minute // 30) * 30, second=0, microsecond=0)
    window_end = min(moment.timestamp() + window_s, (chunk_start + timedelta(minutes=30)).timestamp())
    base = {
        "requested_ts_utc": requested.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "ts_utc": moment.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "clamped_to_latest": clamped,
        "latest_available_utc": _iso(latest_end.timestamp() - 1),
        "bbox": box,
        "fields": REPLAY_FIELDS,
    }
    try:
        path, data = provider.fetch_heatmap_chunk(moment)
        # Start at the slice covering ``moment`` (slices are ~10 s apart).
        chunk = decode_heatmap(data, bbox=tuple(box), start=moment.timestamp() - 15, end=window_end)
    except (ProviderError, HeatmapFormatError) as exc:
        return _unavailable("adsblol.replay", exc, frames=[], **base)
    frames = []
    for item in chunk.slices:
        rows = []
        for pos in item.positions:
            ident = chunk.identities.get(pos.hex, {})
            rows.append([pos.hex, pos.lat, pos.lon, pos.alt_baro, pos.gs, pos.source_type, ident.get("flight"), ident.get("squawk")])
        frames.append({"t": round(item.timestamp, 3), "interval_s": item.interval_s, "aircraft": rows})
    while len(frames) > 1 and frames[1]["t"] <= moment.timestamp():
        frames.pop(0)
    return {
        "feed": "adsblol.replay",
        **base,
        "status": "available" if frames else "empty",
        "reason": None if frames else "No replay slices exist for this time window.",
        "fetched_at_utc": _now_iso(),
        "chunk": {
            "path": path,
            "index": chunk_index(moment),
            "start_utc": _iso(chunk_start.timestamp()),
            "end_utc": _iso((chunk_start + timedelta(minutes=30)).timestamp()),
        },
        "window": {"start_utc": _iso(frames[0]["t"]) if frames else None, "end_utc": _iso(window_end)},
        "frames": frames,
        "source": _source("adsblol.replay", f"{provider.site_base}/{path}"),
    }


@router.post("/routes")
def live_routes(
    payload: Annotated[dict[str, Any], Body(description='{"planes": [{"callsign", "lat", "lng"}]}')],
    provider: LiveProvider,
) -> dict[str, Any]:
    planes = payload.get("planes")
    if not isinstance(planes, list) or not all(isinstance(plane, dict) for plane in planes):
        raise HTTPException(status_code=422, detail="planes must be a list of objects")
    try:
        routes = provider.fetch_routes(planes)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="planes need a callsign and numeric lat/lng") from exc
    except ProviderError as exc:
        return _unavailable("adsblol.routes", exc, routes=[])
    return {
        "feed": "adsblol.routes",
        "status": "available",
        "reason": None,
        "fetched_at_utc": _now_iso(),
        "routes": routes,
        "source": _source("adsblol.routes", f"{provider.api_base}/api/0/routeset"),
    }


def _fetch_openaip_tile(url: str, key: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": adsb_config.ADSBLOL_USER_AGENT, "x-openaip-api-key": key},
    )
    with urllib.request.urlopen(request, timeout=adsb_config.FETCH_TIMEOUT_S) as response:  # noqa: S310 - fixed https base
        return response.read()


def _tile_part(value: int) -> str:
    """Digits-only text for one tile coordinate.

    FastAPI already rejects non-integers and the caller range-checks them; this
    keeps the upstream URL path to plain digits even if those checks change.
    """

    text = str(value)
    if text.isdigit():
        return text
    raise HTTPException(status_code=422, detail="tile coordinates must be non-negative integers")


@router.get("/tiles/openaip/{z}/{x}/{y}.png")
def openaip_tile(z: int, x: int, y: int) -> Response:
    if not 0 <= z <= 14 or not (0 <= x < 2**z and 0 <= y < 2**z):
        raise HTTPException(status_code=422, detail="tile coordinates are out of range")
    key = _openaip_key()
    if not key:
        raise HTTPException(status_code=503, detail="OPENAIP_API_KEY is not configured on the backend")
    url = OPENAIP_TILE_URL.format(z=_tile_part(z), x=_tile_part(x), y=_tile_part(y))
    try:
        body = _fetch_openaip_tile(url, key)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return Response(status_code=204)
        logger.warning("openAIP tile %s/%s/%s failed: HTTP %s", z, x, y, exc.code)
        raise HTTPException(status_code=502, detail="openAIP tile request failed") from exc
    except (urllib.error.URLError, OSError) as exc:
        logger.warning("openAIP tile %s/%s/%s unreachable: %s", z, x, y, exc)
        raise HTTPException(status_code=502, detail="openAIP tile request failed") from exc
    return Response(content=body, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
