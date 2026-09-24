"""Read-only API surface for frozen Space-Track evidence."""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from skywatcher.core.spacetrack import (
    CONTROLLER_CONTRACTS,
    SOURCE_CONTRACTS,
    SpaceTrackStore,
    certify_local_runtime,
    certify_static_contracts,
)

ROOT = Path(__file__).resolve().parents[2]
router = APIRouter(prefix="/api/space-track", tags=["space-track"])


def _store() -> SpaceTrackStore:
    configured = os.environ.get("SKYWATCHER_SPACE_TRACK_ROOT")
    root = Path(configured) if configured else ROOT / "data" / "spacetrack"
    return SpaceTrackStore(root)


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


@router.get("/status")
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
                "object_count": objects.get("object_count", 0) if objects else 0,
                "contradiction_count": len(objects.get("contradictions", [])) if objects else 0,
            },
            "reentry_events": {
                "available": reentry is not None,
                "event_count": len(reentry.get("events", [])) if reentry else 0,
                "contradiction_count": len(reentry.get("contradictions", [])) if reentry else 0,
            },
        },
        "execution": {
            "browser_upstream_calls": False,
            "operator_writes": "HARD_DISABLED",
            "credentials_embedded": False,
            "local_store_present": store.root.exists(),
        },
    }


@router.get("/objects")
def space_track_objects() -> dict[str, Any]:
    value = _store().load_materialization("space_objects")
    if value is None:
        return {
            "state": "NOT_MATERIALIZED",
            "objects": [],
            "contradictions": [],
        }
    return {"state": "AVAILABLE", **value}


@router.get("/reentry")
def space_track_reentry() -> dict[str, Any]:
    value = _store().load_materialization("reentry_events")
    if value is None:
        return {
            "state": "NOT_MATERIALIZED",
            "events": [],
            "contradictions": [],
        }
    return {"state": "AVAILABLE", **value}
