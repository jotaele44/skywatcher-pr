"""Payload builders for the Sky Target Finder endpoints (/api/space-track/sky/*).

Composes the vendored catalog, the observer-frame ephemeris and the frozen
Space-Track materialization into the JSON payloads the GUI reads. Read-only:
nothing here writes to disk or calls an upstream service.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from skywatcher.core.spacetrack import SpaceTrackStore

from .catalog import (
    CatalogObject,
    SearchMatch,
    load_catalog,
    match_query,
    normalize_text,
    search_catalog,
    search_sort_key,
)
from .chart import build_chart_layers, horizontal_separation
from .ephemeris import (
    BodyPosition,
    Observer,
    SkyFrame,
    dark_window,
    solar_system_j2000,
    solar_system_positions,
)
from .filters import filter_hint

try:  # sgp4 is optional at import time: without it satellites report DEPENDENCY_MISSING.
    from sgp4.api import accelerated as _SGP4_ACCELERATED

    from .satellites import (
        MAX_ELEMENT_AGE_DAYS,
        GPElementError,
        element_age_days,
        sun_direction,
        topocentric,
        tracked_objects,
    )

    SGP4_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when sgp4 is not installed
    SGP4_AVAILABLE = False

TARGETS_SCHEMA = "skywatcher.sky-targets/v1"
RECOMMEND_SCHEMA = "skywatcher.sky-recommend/v1"
CHART_SCHEMA = "skywatcher.sky-chart/v1"
DEFAULT_OBSERVER = Observer(18.4655, -66.1057, 10.0)  # San Juan, Puerto Rico
TARGET_KINDS = ("all", "star", "messier", "caldwell", "solar_system", "satellite")
_CATALOG_KINDS = {
    "all": frozenset({"star", "messier", "caldwell"}),
    "star": frozenset({"star"}),
    "messier": frozenset({"messier"}),
    "caldwell": frozenset({"caldwell"}),
    "solar_system": frozenset(),
    "satellite": frozenset(),
}
_RECOMMEND_MIN_ALT_DEG = 30.0
_RECOMMEND_LIMIT = 20
_RECOMMEND_STEP = timedelta(minutes=10)
_SKIPPED_LIMIT = 20
# Keeps visibility arithmetic far from datetime's limits; the ephemerides are not meant for
# deep history or the far future anyway.
_AT_MIN_YEAR = 1800
_AT_MAX_YEAR = 2200


def format_utc(value: datetime | None) -> str | None:
    """Aware datetime -> "YYYY-MM-DDTHH:MM:SSZ" (rounded to the second)."""
    if value is None:
        return None
    rounded = (value.astimezone(timezone.utc) + timedelta(microseconds=500_000)).replace(
        microsecond=0
    )
    return rounded.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_at(value: str | None, now: datetime | None = None) -> datetime:
    """Parse the ``at`` query value (ISO-8601; naive means UTC). Raises ValueError."""
    if value is None or not value.strip():
        return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    if not _AT_MIN_YEAR <= parsed.year <= _AT_MAX_YEAR:
        raise ValueError(f"at must fall between {_AT_MIN_YEAR} and {_AT_MAX_YEAR}")
    return parsed


def _observer_echo(observer: Observer) -> dict[str, float]:
    return {"lat_deg": observer.lat_deg, "lon_deg": observer.lon_deg, "elev_m": observer.elev_m}


def _visibility_dict(visibility) -> dict[str, Any]:
    return {
        "state": visibility.state,
        "rise_utc": format_utc(visibility.rise),
        "set_utc": format_utc(visibility.set),
        "transit_utc": format_utc(visibility.transit),
        "transit_alt_deg": visibility.transit_alt_deg,
    }


def _match_dict(match: SearchMatch | None) -> dict[str, str] | None:
    return {"field": match.field, "text": match.text} if match else None


def catalog_target(
    item: CatalogObject, frame: SkyFrame, match: SearchMatch | None = None
) -> dict[str, Any]:
    """Target JSON for a star or Messier/Caldwell object."""
    alt, az, _ = frame.horizontal(item.ra_deg, item.dec_deg)
    target: dict[str, Any] = {
        "id": item.id,
        "kind": item.kind,
        "designation": item.designation,
        "long_designation": item.long_designation,
        "name": item.name,
        "display": item.display,
        "aliases": list(item.aliases),
        "object_type": item.object_type,
        "constellation": item.constellation,
        "magnitude": item.magnitude,
        "size_arcmin": list(item.size_arcmin) if item.size_arcmin else None,
        "ra_j2000_deg": item.ra_deg,
        "dec_j2000_deg": item.dec_deg,
        "alt_deg": round(alt, 2),
        "az_deg": round(az, 2),
        "above_horizon": alt > 0.0,
        "visibility": _visibility_dict(frame.fixed_visibility(item.ra_deg, item.dec_deg)),
        "filter_hint": filter_hint(item.object_type),
        "satellite": None,
    }
    if match is not None:
        target["match"] = _match_dict(match)
    return target


def body_target(body: BodyPosition, match: SearchMatch | None = None) -> dict[str, Any]:
    """Target JSON for the Sun, Moon or a planet."""
    target: dict[str, Any] = {
        "id": body.id,
        "kind": body.kind,
        "designation": body.name,
        "long_designation": body.name,
        "name": None,
        "display": body.name,
        "aliases": [],
        "object_type": body.kind,
        "constellation": None,
        "magnitude": body.magnitude,
        "size_arcmin": None,
        "ra_j2000_deg": body.ra_j2000_deg,
        "dec_j2000_deg": body.dec_j2000_deg,
        "alt_deg": round(body.alt_deg, 2),
        "az_deg": round(body.az_deg, 2),
        "above_horizon": body.alt_deg > 0.0,
        "visibility": _visibility_dict(body.visibility),
        "filter_hint": None,
        "satellite": None,
    }
    if match is not None:
        target["match"] = _match_dict(match)
    return target


# ---------------------------------------------------------------------------
# Satellites
# ---------------------------------------------------------------------------


@dataclass
class SatelliteLayer:
    """Propagated satellites plus the honest state of the Space-Track source."""

    state: str  # NOT_MATERIALIZED | AVAILABLE | DEPENDENCY_MISSING
    object_count: int | None = None
    targets: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "object_count": self.object_count,
            "propagated": len(self.targets),
            "skipped_count": len(self.skipped),
            "skipped": self.skipped[:_SKIPPED_LIMIT],
        }


_TRACKED_CACHE: dict[tuple[str, int, int], tuple[list, list, int]] = {}
_TRACKED_LOCK = threading.Lock()


def _tracked(store: SpaceTrackStore) -> tuple[list, list, int] | None:
    path = store.root / "materialized" / "space_objects" / "current.json"
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    # The C-accelerated Satrec is safe to share across threads (each call holds the GIL);
    # the pure-Python fallback mutates state while propagating, so it is never cached.
    if _SGP4_ACCELERATED:
        with _TRACKED_LOCK:
            cached = _TRACKED_CACHE.get(key)
        if cached is not None:
            return cached
    materialization = store.load_materialization("space_objects")
    if materialization is None:
        return None
    tracked, skipped = tracked_objects(materialization)
    result = (tracked, skipped, len(materialization.get("objects", ())))
    if _SGP4_ACCELERATED:
        with _TRACKED_LOCK:
            _TRACKED_CACHE.clear()
            _TRACKED_CACHE[key] = result
    return result


def _satellite_target(obj, position, match: SearchMatch | None = None) -> dict[str, Any]:
    designation = f"NORAD {obj.norad_cat_id}"
    aliases = sorted({*obj.aliases, designation, *([obj.object_id] if obj.object_id else [])})
    target = {
        "id": f"satellite:norad:{obj.norad_cat_id}",
        "kind": "satellite",
        "designation": designation,
        "long_designation": obj.name or designation,
        "name": obj.name,
        # A satellite reads by its object name ("ISS (ZARYA)"); NORAD id is the fallback.
        "display": obj.name or designation,
        "aliases": [alias for alias in aliases if alias != obj.name],
        "object_type": (obj.object_type or "satellite").lower(),
        "constellation": None,
        "magnitude": None,
        "size_arcmin": None,
        "ra_j2000_deg": round(position.ra_j2000_deg, 4),
        "dec_j2000_deg": round(position.dec_j2000_deg, 4),
        "alt_deg": round(position.alt_deg, 2),
        "az_deg": round(position.az_deg, 2),
        "above_horizon": position.alt_deg > 0.0,
        "visibility": {
            "state": "UP" if position.alt_deg > 0.0 else "DOWN",
            "rise_utc": None,
            "set_utc": None,
            "transit_utc": None,
            "transit_alt_deg": None,
        },
        "filter_hint": None,
        "satellite": {
            "norad_cat_id": obj.norad_cat_id,
            "object_id": obj.object_id,
            "range_km": round(position.range_km, 1),
            "sunlit": position.sunlit,
            "element_epoch": format_utc(position.element_epoch),
            "element_age_days": round(position.element_age_days, 2),
            "identity_state": obj.identity_state,
        },
    }
    if match is not None:
        target["match"] = _match_dict(match)
    return target


def satellite_layer(
    store: SpaceTrackStore,
    frame: SkyFrame,
    select: Callable[[Any], bool] | None = None,
) -> SatelliteLayer:
    """Propagate the frozen Space-Track objects (all, or those ``select`` keeps) to the frame time.

    ``select=lambda _: False`` reports the source state without propagating anything.
    """
    if not SGP4_AVAILABLE:
        return SatelliteLayer("DEPENDENCY_MISSING")
    tracked = _tracked(store)
    if tracked is None:
        return SatelliteLayer("NOT_MATERIALIZED")
    objects, skipped, object_count = tracked
    layer = SatelliteLayer("AVAILABLE", object_count=object_count, skipped=list(skipped))
    if select is not None:
        objects = [obj for obj in objects if select(obj)]
    at_date = frame.at.date().isoformat()
    sun_unit = sun_direction(frame) if objects else (1.0, 0.0, 0.0)
    for obj in objects:
        if obj.decay_date and obj.decay_date[:10] <= at_date:
            layer.skipped.append({"norad_cat_id": obj.norad_cat_id, "reason": "decayed"})
            continue
        age = element_age_days(obj.satellite, frame.at)
        if abs(age) > MAX_ELEMENT_AGE_DAYS:
            layer.skipped.append(
                {"norad_cat_id": obj.norad_cat_id, "reason": f"elements {age:.0f} days from epoch"}
            )
            continue
        try:
            position = topocentric(obj.satellite, frame, sun_unit)
        except GPElementError as exc:
            layer.skipped.append({"norad_cat_id": obj.norad_cat_id, "reason": str(exc)})
            continue
        layer.targets.append(_satellite_target(obj, position))
    return layer


def _tracked_fields(obj) -> Iterator[tuple[str, str]]:
    yield "designation", f"NORAD {obj.norad_cat_id}"
    if obj.name:
        yield "name", obj.name
    for alias in (*obj.aliases, obj.object_id, obj.norad_cat_id):
        if alias:
            yield "alias", alias


def _satellite_fields(target: dict[str, Any]) -> Iterator[tuple[str, str]]:
    yield "designation", target["designation"]
    if target["name"]:
        yield "name", target["name"]
    for alias in target["aliases"]:
        yield "alias", alias
    yield "alias", target["satellite"]["norad_cat_id"]


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


def targets_payload(
    *,
    catalog_dir: Path,
    store: SpaceTrackStore,
    observer: Observer,
    at: datetime,
    q: str = "",
    kind: str = "all",
    limit: int = 50,
) -> dict[str, Any]:
    """GET /api/space-track/sky/targets."""
    if kind not in TARGET_KINDS:
        raise ValueError(f"kind must be one of {', '.join(TARGET_KINDS)}")
    catalog = load_catalog(catalog_dir)
    frame = SkyFrame(observer, at)
    include_bodies = kind in ("all", "solar_system")
    include_satellites = kind in ("all", "satellite")
    bodies = solar_system_positions(frame) if include_bodies else ()
    query = normalize_text(q)
    # Propagate only what can appear: nothing for non-satellite kinds, name matches for a search.
    if not include_satellites:
        satellites = satellite_layer(store, frame, select=lambda _obj: False)
    elif query:
        satellites = satellite_layer(
            store, frame, select=lambda obj: match_query(query, _tracked_fields(obj)) is not None
        )
    else:
        satellites = satellite_layer(store, frame)

    # Catalog hits stay (object, match) pairs so only the returned page pays for visibility.
    ranked: list[tuple[tuple, tuple[CatalogObject, SearchMatch] | dict[str, Any]]] = []
    if query:
        for item, match in search_catalog(catalog, q, _CATALOG_KINDS[kind]):
            ranked.append((search_sort_key(match, item.magnitude, item.display), (item, match)))
        for body in bodies:
            body_match = match_query(query, [("designation", body.name)])
            if body_match:
                ranked.append(
                    (
                        search_sort_key(body_match, body.magnitude, body.name),
                        body_target(body, body_match),
                    )
                )
        if include_satellites:
            for sat_target in satellites.targets:
                sat_match = match_query(query, _satellite_fields(sat_target))
                if sat_match:
                    ranked.append(
                        (
                            search_sort_key(sat_match, None, sat_target["display"]),
                            {**sat_target, "match": _match_dict(sat_match)},
                        )
                    )
        ranked.sort(key=lambda pair: pair[0])
        selected = ranked[:limit]
        targets = [
            catalog_target(value[0], frame, value[1]) if isinstance(value, tuple) else value
            for _, value in selected
        ]
    else:
        visible: list[tuple[tuple, Any]] = []
        kinds = _CATALOG_KINDS[kind]
        for item in catalog.objects:
            if item.kind not in kinds:
                continue
            alt, _az, _ = frame.horizontal(item.ra_deg, item.dec_deg)
            if alt > 0.0:
                mag = item.magnitude if item.magnitude is not None else float("inf")
                visible.append(((0, mag, item.display.casefold()), item))
        for body in bodies:
            if body.alt_deg > 0.0:
                visible.append(((0, body.magnitude, body.name.casefold()), body_target(body)))
        if include_satellites:
            for target in satellites.targets:
                if target["above_horizon"]:
                    visible.append(((1, -target["alt_deg"], target["display"].casefold()), target))
        visible.sort(key=lambda pair: pair[0])
        targets = [
            catalog_target(value, frame) if isinstance(value, CatalogObject) else value
            for _, value in visible[:limit]
        ]

    return {
        "schema_version": TARGETS_SCHEMA,
        "observer": _observer_echo(observer),
        "at_utc": format_utc(frame.at),
        "query": q,
        "kind": kind,
        "count": len(targets),
        "targets": targets,
        "satellites": satellites.summary(),
        "catalog": {"schema_version": catalog.schema_version, "data_license": catalog.data_license},
    }


def _recommend_candidates(catalog, frame: SkyFrame) -> list[tuple[str, float, float]]:
    candidates = [
        (item.id, item.ra_deg, item.dec_deg)
        for item in catalog.objects
        if item.kind in ("messier", "caldwell")
    ]
    candidates.extend(solar_system_j2000(frame))
    return candidates


@lru_cache(maxsize=32)
def _ranked_for_window(
    catalog_dir: str, lat: float, lon: float, elev: float, start_iso: str, end_iso: str
) -> tuple[tuple[str, float, str], ...]:
    """Best altitude of every candidate inside one dark window (cached per night)."""
    observer = Observer(lat, lon, elev)
    start, end = datetime.fromisoformat(start_iso), datetime.fromisoformat(end_iso)
    catalog = load_catalog(Path(catalog_dir))
    samples = []
    moment = start
    while moment <= end:
        samples.append(SkyFrame(observer, moment))
        moment += _RECOMMEND_STEP
    if samples[-1].at < end:
        samples.append(SkyFrame(observer, end))
    best: dict[str, tuple[float, datetime]] = {}
    for frame in samples:
        positions = {item[0]: (item[1], item[2]) for item in _recommend_candidates(catalog, frame)}
        for target_id, (ra, dec) in positions.items():
            alt, _az, _ = frame.horizontal(ra, dec)
            if target_id not in best or alt > best[target_id][0]:
                best[target_id] = (alt, frame.at)
    return tuple(
        (target_id, round(alt, 2), format_utc(when) or "") for target_id, (alt, when) in best.items()
    )


def recommend_payload(*, catalog_dir: Path, observer: Observer, at: datetime) -> dict[str, Any]:
    """GET /api/space-track/sky/recommend."""
    catalog = load_catalog(catalog_dir)
    frame = SkyFrame(observer, at)
    window = dark_window(frame, -12.0)
    targets: list[dict[str, Any]] = []
    if window is not None:
        start, end = window
        ranked = _ranked_for_window(
            str(catalog_dir),
            round(observer.lat_deg, 4),
            round(observer.lon_deg, 4),
            round(observer.elev_m, 1),
            start.replace(microsecond=0).isoformat(),
            end.replace(microsecond=0).isoformat(),
        )
        bodies = {body.id: body for body in solar_system_positions(frame)}
        scored = []
        for target_id, best_alt, best_utc in ranked:
            if best_alt < _RECOMMEND_MIN_ALT_DEG:
                continue
            item = catalog.by_id.get(target_id)
            target = catalog_target(item, frame) if item else body_target(bodies[target_id])
            magnitude = target["magnitude"]
            brightness = 0.3 if magnitude is None else min(1.0, max(0.0, (10.0 - magnitude) / 10.0))
            score = 0.7 * (best_alt / 90.0) + 0.3 * brightness
            target["recommend"] = {
                "best_alt_deg": best_alt,
                "best_utc": best_utc,
                "score": round(score, 3),
            }
            scored.append(target)
        scored.sort(key=lambda t: (-t["recommend"]["score"], t["display"].casefold()))
        targets = scored[:_RECOMMEND_LIMIT]
    return {
        "schema_version": RECOMMEND_SCHEMA,
        "observer": _observer_echo(observer),
        "at_utc": format_utc(frame.at),
        "dark_window": (
            {"start_utc": format_utc(window[0]), "end_utc": format_utc(window[1]),
             "sun_alt_deg": -12.0}
            if window
            else None
        ),
        "targets": targets,
    }


def chart_payload(
    *,
    catalog_dir: Path,
    store: SpaceTrackStore,
    observer: Observer,
    at: datetime,
    target_id: str,
    fov_deg: float = 6.0,
    radius_deg: float | None = None,
) -> dict[str, Any]:
    """GET /api/space-track/sky/chart. Raises LookupError for an unknown target."""
    catalog = load_catalog(catalog_dir)
    frame = SkyFrame(observer, at)
    radius = radius_deg if radius_deg is not None else max(2.0 * fov_deg, 10.0)
    bodies = solar_system_positions(frame)
    satellites = satellite_layer(store, frame)

    target: dict[str, Any] | None
    item = catalog.get(target_id)
    if item is not None:
        target = catalog_target(item, frame)
    else:
        body = next((b for b in bodies if b.id == target_id), None)
        if body is not None:
            target = body_target(body)
        else:
            target = next((t for t in satellites.targets if t["id"] == target_id), None)
    if target is None:
        raise LookupError(f"Unknown sky target: {target_id}")

    center_alt, center_az = target["alt_deg"], target["az_deg"]
    layers = build_chart_layers(
        catalog,
        frame,
        center_ra=target["ra_j2000_deg"],
        center_dec=target["dec_j2000_deg"],
        center_alt=center_alt,
        center_az=center_az,
        fov_deg=fov_deg,
        radius_deg=radius,
        exclude_id=target["id"],
    )
    solar = [
        {"id": b.id, "display": b.name, "alt": round(b.alt_deg, 3), "az": round(b.az_deg, 3),
         "magnitude": b.magnitude}
        for b in bodies
        if b.id != target["id"]
        and horizontal_separation(b.alt_deg, b.az_deg, center_alt, center_az) <= radius
    ]
    sats = [
        {"id": t["id"], "display": t["display"], "alt": t["alt_deg"], "az": t["az_deg"],
         "sunlit": t["satellite"]["sunlit"]}
        for t in satellites.targets
        if t["id"] != target["id"]
        and horizontal_separation(t["alt_deg"], t["az_deg"], center_alt, center_az) <= radius
    ]
    return {
        "schema_version": CHART_SCHEMA,
        "observer": _observer_echo(observer),
        "at_utc": format_utc(frame.at),
        "fov_deg": fov_deg,
        "radius_deg": radius,
        "target": target,
        **layers,
        "solar_system": solar,
        "satellites": sats,
    }
