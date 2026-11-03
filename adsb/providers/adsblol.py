"""
adsb.lol provider — keyless community ADS-B aggregator (data: ODbL-1.0).

Covers every aircraft data source the adsb.lol web map uses, through public
endpoints only:

* live positions — ``api.adsb.lol/v2/point/{lat}/{lon}/{radius_nm}``
  (documented public API; the radius is capped at 250 NM upstream);
* military-only view — ``api.adsb.lol/v2/mil``;
* selected aircraft outside the view — ``api.adsb.lol/v2/hex/{hex}``;
* per-aircraft tracks — ``adsb.lol/data/traces/..`` (today) and
  ``adsb.lol/globe_history/YYYY/MM/DD/traces/..`` (past days);
* replay — ``adsb.lol/globe_history/YYYY/MM/DD/heatmap/NN.bin.ttf``
  half-hour chunks, decoded by :mod:`adsb.heatmap`;
* flight routes — ``api.adsb.lol/api/0/routeset``.

The web map's internal ``re-api`` endpoint is protected by a bot-verification
challenge and is intentionally not used. Transport is stdlib ``urllib`` so the
core stays dependency-free; identical requests within ``ADSBLOL_CACHE_TTL_S``
are answered from memory to keep load on the community service low.
"""

from __future__ import annotations

import gzip
import json
import math
import re
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .. import config
from ..heatmap import chunk_path
from ..models import StateVector
from .base import AdsbProvider, ProviderError

ATTRIBUTION = "adsb.lol contributors (ODbL 1.0)"
LICENSE = "ODbL-1.0"
HEX_RE = re.compile(r"^~?[0-9a-f]{6}$")
FT_TO_M = 0.3048
KT_TO_MS = 0.514444
FPM_TO_MS = 0.00508
EARTH_RADIUS_NM = 3440.065

Opener = Callable[[urllib.request.Request, float], tuple[int, dict[str, str], bytes]]


def _default_opener(request: urllib.request.Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https bases
        headers = {key.lower(): value for key, value in response.headers.items()}
        return response.status, headers, response.read()


def normalize_hex(value: str) -> str:
    candidate = (value or "").strip().lower()
    if not HEX_RE.match(candidate):
        raise ProviderError(f"invalid ICAO hex address: {value!r}")
    return candidate


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(a)))


def bbox_query_circle(bbox: list[float], max_radius_nm: float) -> dict[str, Any]:
    """Smallest centred circle covering ``bbox`` (west, south, east, north),
    clamped to the upstream radius cap."""

    west, south, east, north = (float(v) for v in bbox[:4])
    if not (-90 <= south < north <= 90) or not (-180 <= west <= 180 and -180 <= east <= 180):
        raise ProviderError(f"invalid bbox: {bbox!r}")
    span = east - west if east >= west else east + 360 - west
    lon = west + span / 2
    if lon > 180:
        lon -= 360
    lat = (south + north) / 2
    needed = max(
        haversine_nm(lat, lon, corner_lat, corner_lon)
        for corner_lat in (south, north)
        for corner_lon in (west, east)
    )
    radius = min(math.ceil(needed), max_radius_nm)
    return {
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "radius_nm": radius,
        "required_radius_nm": round(needed, 1),
        "complete": needed <= max_radius_nm,
    }


def in_bbox(lat: Any, lon: Any, bbox: list[float]) -> bool:
    if lat is None or lon is None:
        return False
    west, south, east, north = bbox[:4]
    if not south <= lat <= north:
        return False
    return west <= lon <= east if west <= east else (lon >= west or lon <= east)


def decode_trace(payload: dict[str, Any]) -> dict[str, Any]:
    """Expand a readsb trace file into absolute-time points.

    Row layout: ``[dt, lat, lon, alt, gs, track, flags, vrate, aircraft|null,
    source_type, alt_geom, geom_rate, ias, roll]``. Flag bit 0 marks a stale
    position, bit 1 the start of a new leg.
    """

    base = float(payload.get("timestamp") or 0)
    points: list[dict[str, Any]] = []
    flight = None
    for row in payload.get("trace") or []:
        if not isinstance(row, list) or len(row) < 6:
            continue
        flags = int(row[6]) if len(row) > 6 and row[6] is not None else 0
        details = row[8] if len(row) > 8 and isinstance(row[8], dict) else None
        if details and details.get("flight"):
            flight = str(details["flight"]).strip() or flight
        points.append(
            {
                "t": round(base + float(row[0]), 3),
                "lat": row[1],
                "lon": row[2],
                "alt_baro": row[3],
                "gs": row[4],
                "track": row[5],
                "stale": bool(flags & 1),
                "new_leg": bool(flags & 2),
                "baro_rate": row[7] if len(row) > 7 else None,
                "source_type": row[9] if len(row) > 9 else None,
                "alt_geom": row[10] if len(row) > 10 else None,
                "flight": flight,
            }
        )
    return {
        "hex": payload.get("icao"),
        "registration": payload.get("r"),
        "type": payload.get("t"),
        "description": payload.get("desc"),
        "operator": payload.get("ownOp"),
        "year": payload.get("year"),
        "db_flags": payload.get("dbFlags"),
        "points": points,
    }


def route_summary(route: dict[str, Any]) -> dict[str, Any]:
    """Flatten a routeset entry: ``_airports`` -> "SJU - MIA" plus cities."""

    airports = [a for a in route.get("_airports") or [] if isinstance(a, dict)]
    codes = " - ".join(str(a.get("iata") or a.get("icao") or "?") for a in airports)
    cities = " - ".join(str(a.get("location") or "") for a in airports if a.get("location"))
    if codes and route.get("plausible") is False:
        codes = f"?? {codes}"
    return {
        "callsign": route.get("callsign"),
        "route": codes or None,
        "cities": cities or None,
        "plausible": route.get("plausible"),
        "airports": [
            {"iata": a.get("iata"), "icao": a.get("icao"), "location": a.get("location")} for a in airports
        ],
    }


class AdsbLolProvider(AdsbProvider):
    """Live, historical and replay aircraft data from adsb.lol."""

    name = "adsblol"

    def __init__(
        self,
        *,
        api_base: str | None = None,
        site_base: str | None = None,
        cache_dir: Path | None = None,
        opener: Opener | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.api_base = (api_base or config.ADSBLOL_API_BASE).rstrip("/")
        self.site_base = (site_base or config.ADSBLOL_SITE_BASE).rstrip("/")
        self.cache_dir = Path(cache_dir) if cache_dir is not None else config.ADSBLOL_CACHE_DIR
        self._open = opener or _default_opener
        self._clock = clock
        self._memo: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._chunks: OrderedDict[str, bytes] = OrderedDict()
        self._lock = threading.Lock()

    # ── transport ────────────────────────────────────────────────────────────
    def _request(
        self,
        url: str,
        *,
        body: bytes | None = None,
        ttl: float | None = None,
        timeout: float | None = None,
    ) -> bytes:
        ttl = config.ADSBLOL_CACHE_TTL_S if ttl is None else ttl
        key = url if body is None else f"{url}\n{body!r}"
        now = self._clock()
        if ttl > 0:
            with self._lock:
                cached = self._memo.get(key)
                if cached and now - cached[0] < ttl:
                    return cached[1]
        headers = {"User-Agent": config.ADSBLOL_USER_AGENT, "Accept-Encoding": "gzip"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        last_exc: Exception | None = None
        for attempt in range(max(1, config.FETCH_RETRIES)):
            request = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
            try:
                status, response_headers, raw = self._open(request, timeout or config.FETCH_TIMEOUT_S)
            except urllib.error.HTTPError as exc:
                if exc.code in (400, 403, 404, 410, 422):
                    raise ProviderError(f"adsb.lol returned HTTP {exc.code} for {url}") from exc
                last_exc = exc
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                last_exc = exc
            else:
                if status >= 400:
                    raise ProviderError(f"adsb.lol returned HTTP {status} for {url}")
                if response_headers.get("content-encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                    try:
                        raw = gzip.decompress(raw)
                    except OSError as exc:
                        raise ProviderError(f"adsb.lol sent an unreadable gzip body for {url}") from exc
                if ttl > 0:
                    with self._lock:
                        self._memo[key] = (now, raw)
                        while len(self._memo) > 64:
                            self._memo.popitem(last=False)
                return raw
            if attempt < config.FETCH_RETRIES - 1:
                time.sleep(0.5 * (attempt + 1))
        raise ProviderError(f"adsb.lol request failed after {config.FETCH_RETRIES} attempts: {last_exc}")

    def _json(self, url: str, **kwargs: Any) -> Any:
        raw = self._request(url, **kwargs)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError(f"adsb.lol sent invalid JSON for {url}") from exc

    # ── live aircraft ────────────────────────────────────────────────────────
    def fetch_aircraft(
        self,
        bbox: list[float],
        *,
        military: bool = False,
        hexes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Aircraft inside ``bbox`` plus any explicitly requested ``hexes``."""

        circle = bbox_query_circle(bbox, config.ADSBLOL_MAX_RADIUS_NM)
        if military:
            url = f"{self.api_base}/v2/mil"
            coverage = {"mode": "military_global", "complete": True}
        else:
            url = f"{self.api_base}/v2/point/{circle['lat']}/{circle['lon']}/{circle['radius_nm']:g}"
            coverage = {"mode": "point_radius", **circle}
        payload = self._json(url)
        aircraft = [ac for ac in payload.get("ac") or [] if in_bbox(ac.get("lat"), ac.get("lon"), bbox)]
        seen = {ac.get("hex") for ac in aircraft}
        for hex_id in [normalize_hex(h) for h in (hexes or [])][:20]:
            if hex_id in seen:
                continue
            extra = self._json(f"{self.api_base}/v2/hex/{hex_id}")
            for ac in extra.get("ac") or []:
                if ac.get("hex") not in seen:
                    aircraft.append({**ac, "outside_view": True})
                    seen.add(ac.get("hex"))
        return {
            "now": payload.get("now"),
            "aircraft": aircraft,
            "upstream_total": payload.get("total"),
            "coverage": coverage,
            "upstream_url": url,
        }

    def fetch_states(self, bbox: list[float]) -> list[StateVector]:
        """Poller contract: SI-unit state vectors (OpenSky conventions)."""

        result = self.fetch_aircraft(bbox)
        now_s = (result.get("now") or self._clock() * 1000) / 1000
        return [self._to_state_vector(ac, now_s) for ac in result["aircraft"]]

    def _to_state_vector(self, ac: dict[str, Any], now_s: float) -> StateVector:
        def scaled(value: Any, factor: float) -> float | None:
            return round(float(value) * factor, 2) if isinstance(value, (int, float)) else None

        seen_pos = ac.get("seen_pos")
        seen = ac.get("seen")
        alt_baro = ac.get("alt_baro")
        return StateVector(
            icao24=str(ac.get("hex", "")).lstrip("~"),
            callsign=(str(ac.get("flight") or "").strip() or None),
            origin_country=None,
            time_position=int(now_s - seen_pos) if isinstance(seen_pos, (int, float)) else None,
            last_contact=int(now_s - seen) if isinstance(seen, (int, float)) else None,
            longitude=ac.get("lon"),
            latitude=ac.get("lat"),
            baro_altitude=scaled(alt_baro, FT_TO_M),
            on_ground=alt_baro == "ground",
            velocity=scaled(ac.get("gs"), KT_TO_MS),
            true_track=ac.get("track"),
            vertical_rate=scaled(ac.get("baro_rate", ac.get("geom_rate")), FPM_TO_MS),
            geo_altitude=scaled(ac.get("alt_geom"), FT_TO_M),
            squawk=ac.get("squawk"),
            position_source=None,
            provider=self.name,
        )

    # ── traces ───────────────────────────────────────────────────────────────
    def fetch_trace(self, hex_id: str, day: date | None = None) -> dict[str, Any]:
        """Full-day trace for one aircraft; today's live file when ``day`` is
        None or today (UTC), otherwise the archived ``globe_history`` file."""

        hex_id = normalize_hex(hex_id)
        today = datetime.fromtimestamp(self._clock(), timezone.utc).date()
        if day is None or day >= today:
            path = f"data/traces/{hex_id[-2:]}/trace_full_{hex_id}.json"
        else:
            path = f"globe_history/{day:%Y/%m/%d}/traces/{hex_id[-2:]}/trace_full_{hex_id}.json"
        url = f"{self.site_base}/{path}"
        decoded = decode_trace(self._json(url, ttl=15))
        decoded["upstream_url"] = url
        return decoded

    # ── replay ───────────────────────────────────────────────────────────────
    def latest_complete_chunk_start(self) -> datetime:
        now = datetime.fromtimestamp(self._clock(), timezone.utc)
        floor = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
        return floor - timedelta(minutes=30)

    def fetch_heatmap_chunk(self, moment: datetime) -> tuple[str, bytes]:
        """Raw (decompressed) replay chunk containing ``moment``.

        Completed chunks are immutable upstream and are cached on disk; the
        chunk for the current half hour is still growing and is never cached.
        """

        moment = moment.astimezone(timezone.utc)
        rel = chunk_path(moment)
        with self._lock:
            if rel in self._chunks:
                self._chunks.move_to_end(rel)
                return rel, self._chunks[rel]
        chunk_end = moment.replace(minute=(moment.minute // 30) * 30, second=0, microsecond=0) + timedelta(minutes=30)
        complete = chunk_end.timestamp() <= self._clock() - 300
        disk = self.cache_dir / rel
        data: bytes | None = None
        if complete and disk.is_file():
            data = disk.read_bytes()
        if data is None:
            data = self._request(f"{self.site_base}/{rel}", ttl=0, timeout=max(60, config.FETCH_TIMEOUT_S))
            if complete:
                try:
                    disk.parent.mkdir(parents=True, exist_ok=True)
                    tmp = disk.with_suffix(".part")
                    tmp.write_bytes(data)
                    tmp.replace(disk)
                except OSError:
                    pass  # the cache is an optimisation only
        if complete:
            with self._lock:
                self._chunks[rel] = data
                while len(self._chunks) > 2:
                    self._chunks.popitem(last=False)
        return rel, data

    # ── routes ───────────────────────────────────────────────────────────────
    def fetch_routes(self, planes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned = []
        for plane in planes[:100]:
            callsign = str(plane.get("callsign") or "").strip().upper()
            if not callsign or not re.match(r"^[A-Z0-9]{2,8}$", callsign):
                continue
            cleaned.append(
                {"callsign": callsign, "lat": float(plane.get("lat") or 0), "lng": float(plane.get("lng") or 0)}
            )
        if not cleaned:
            return []
        body = json.dumps({"planes": cleaned}).encode("utf-8")
        raw = self._request(f"{self.api_base}/api/0/routeset", body=body, ttl=60)
        if not raw.strip():
            return []  # upstream answers 201 with no body when it knows no route
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("adsb.lol sent invalid JSON for routeset") from exc
        return [route_summary(item) for item in result if isinstance(item, dict)] if isinstance(result, list) else []
