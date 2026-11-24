"""Read-only API surface for frozen Space-Track evidence and the Sky Target Finder."""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from skywatcher.core.spacetrack import (
    CONTROLLER_CONTRACTS,
    SOURCE_CONTRACTS,
    SpaceTrackStore,
    certify_local_runtime,
    certify_static_contracts,
)

try:  # astronomy-engine is a backend requirement; degrade to 503 rather than fail startup.
    from skywatcher.core import sky as sky_service
except ImportError:  # pragma: no cover - exercised only when astronomy-engine is missing
    sky_service = None

ROOT = Path(__file__).resolve().parents[2]
router = APIRouter(tags=["space-track"])
SkyKind = Literal["all", "star", "messier", "caldwell", "solar_system", "satellite"]


def _store() -> SpaceTrackStore:
    configured = os.environ.get("SKYWATCHER_SPACE_TRACK_ROOT")
    root = Path(configured) if configured else ROOT / "data" / "spacetrack"
    return SpaceTrackStore(root)


def _sky_catalog_dir() -> Path:
    configured = os.environ.get("SKYWATCHER_SKY_CATALOG_DIR")
    return Path(configured) if configured else ROOT / "data" / "reference" / "sky"


def _sky_request(lat: float, lon: float, elev_m: float, at: str | None):
    if sky_service is None:
        raise HTTPException(
            status_code=503,
            detail={"state": "DEPENDENCY_MISSING", "missing": ["astronomy-engine"]},
        )
    try:
        moment = sky_service.parse_at(at)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="at must be an ISO-8601 timestamp, e.g. 2026-10-20T00:30:00Z"
        ) from exc
    return sky_service.Observer(lat, lon, elev_m), moment


def _source_status(store: SpaceTrackStore) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for contract in SOURCE_CONTRACTS:
        batches = store.load_normalized_batches(contract.source_id)
        schema = store.load_schema(contract.source_id) if contract.schema_required else None
        watermark = store.load_watermark(contract.source_id)
        rows.append(
            {
                "source_id": contract.source_id,
                "priority": contract.priority,
                "role": contract.role,
                "controller": contract.controller,
                "canonical_role": contract.canonical_role,
                "batch_count": len(batches),
                "schema_state": (
                    "ACCEPTED"
                    if schema is not None
                    else "NOT_REQUIRED"
                    if not contract.schema_required
                    else "MISSING"
                ),
                "watermark": asdict(watermark) if watermark is not None else None,
                "query_once": contract.query_once,
                "distribution_class": contract.distribution_class.value,
            }
        )
    return rows


@router.get("/api/space-track/status")
def space_track_status() -> dict[str, Any]:
    store = _store()
    static = certify_static_contracts()
    runtime = certify_local_runtime(store)
    objects = store.load_materialization("space_objects")
    reentry = store.load_materialization("reentry_events")
    return {
        "schema_version": "skywatcher.space-track-status/v1",
        "static_contract": asdict(static),
        "runtime": asdict(runtime),
        "controllers": [asdict(item) for item in CONTROLLER_CONTRACTS],
        "sources": _source_status(store),
        "materializations": {
            "space_objects": {
                "available": objects is not None,
                "object_count": objects.get("object_count") if objects is not None else None,
                "contradiction_count": len(objects["contradictions"]) if objects is not None and "contradictions" in objects else None,
            },
            "reentry_events": {
                "available": reentry is not None,
                "event_count": len(reentry["events"]) if reentry is not None and "events" in reentry else None,
                "contradiction_count": len(reentry["contradictions"]) if reentry is not None and "contradictions" in reentry else None,
            },
        },
        "execution": {
            "browser_upstream_calls": False,
            "operator_writes": "HARD_DISABLED",
            "credentials_embedded": False,
            "local_store_present": store.root.exists(),
        },
    }


@router.get("/api/space-track/objects")
def space_track_objects() -> dict[str, Any]:
    value = _store().load_materialization("space_objects")
    if value is None:
        return {
            "state": "NOT_MATERIALIZED",
            "objects": [],
            "contradictions": [],
        }
    return {"state": "AVAILABLE", **value}


@router.get("/api/space-track/reentry")
def space_track_reentry() -> dict[str, Any]:
    value = _store().load_materialization("reentry_events")
    if value is None:
        return {
            "state": "NOT_MATERIALIZED",
            "events": [],
            "contradictions": [],
        }
    return {"state": "AVAILABLE", **value}


# Observer defaults: San Juan, Puerto Rico (skywatcher.core.sky.DEFAULT_OBSERVER).
_LAT = Query(18.4655, ge=-90.0, le=90.0)
_LON = Query(-66.1057, ge=-180.0, le=180.0)
_ELEV = Query(10.0, ge=-500.0, le=10000.0)
_AT = Query(None, max_length=40)
_KIND = Query("all")


@router.get("/api/space-track/sky/targets")
def space_track_sky_targets(
    q: str = Query("", max_length=100),
    kind: SkyKind = _KIND,
    limit: int = Query(50, ge=1, le=200),
    lat: float = _LAT,
    lon: float = _LON,
    elev_m: float = _ELEV,
    at: str | None = _AT,
) -> dict[str, Any]:
    observer, moment = _sky_request(lat, lon, elev_m, at)
    return sky_service.targets_payload(
        catalog_dir=_sky_catalog_dir(),
        store=_store(),
        observer=observer,
        at=moment,
        q=q,
        kind=kind,
        limit=limit,
    )


@router.get("/api/space-track/sky/recommend")
def space_track_sky_recommend(
    lat: float = _LAT,
    lon: float = _LON,
    elev_m: float = _ELEV,
    at: str | None = _AT,
) -> dict[str, Any]:
    observer, moment = _sky_request(lat, lon, elev_m, at)
    return sky_service.recommend_payload(
        catalog_dir=_sky_catalog_dir(), observer=observer, at=moment
    )


@router.get("/api/space-track/sky/chart")
def space_track_sky_chart(
    target: str = Query(..., min_length=1, max_length=80),
    fov_deg: float = Query(6.0, ge=0.5, le=60.0),
    radius_deg: float | None = Query(None, ge=1.0, le=90.0),
    lat: float = _LAT,
    lon: float = _LON,
    elev_m: float = _ELEV,
    at: str | None = _AT,
) -> dict[str, Any]:
    observer, moment = _sky_request(lat, lon, elev_m, at)
    try:
        return sky_service.chart_payload(
            catalog_dir=_sky_catalog_dir(),
            store=_store(),
            observer=observer,
            at=moment,
            target_id=target,
            fov_deg=fov_deg,
            radius_deg=radius_deg,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown sky target: {target}") from exc
