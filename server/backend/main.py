"""FastAPI diagnostic backend over committed Skywatcher artifacts."""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import secrets
import threading
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

ROOT = Path(__file__).resolve().parents[2]
AIRPORTS_PATH = ROOT / "data" / "reference" / "pr_airports.jsonl"
EXPORTS_DIR = ROOT / "exports"
SYNTHETIC_PACKAGE = EXPORTS_DIR / "examples" / "synthetic_airspace_package"
EVIDENCE_PATH = ROOT / "reports" / "federation" / "evidence_skywatcher-pr.jsonl"
MAX_PAGE_SIZE = 1_000
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_PAYLOAD_FIELDS = 128
RESERVED_FIELDS = {"id", "_process_overlay"}

app = FastAPI(
    title="Skywatcher-PR Dashboard API",
    description="Diagnostic federation entity API over committed Skywatcher artifacts.",
    version="0.3.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
log = logging.getLogger("skywatcher.backend")
_WRITE_ENABLED = os.environ.get("PRII_ENABLE_WRITES", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_WRITE_TOKEN = os.environ.get("PRII_WRITE_TOKEN", "")


class EntityPayload(RootModel[dict[str, Any]]):
    """Bounded review-overlay payload with server-owned identity fields."""

    @model_validator(mode="after")
    def validate_payload(self):
        reserved = sorted(set(self.root) & RESERVED_FIELDS)
        if reserved:
            raise ValueError(f"reserved fields are server-owned: {reserved}")
        if len(self.root) > MAX_PAYLOAD_FIELDS:
            raise ValueError("too many payload fields")
        if len(json.dumps(self.root, default=str).encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError("payload exceeds size limit")
        return self


class FilterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: dict[str, Any] = Field(default_factory=dict)
    sort: str = ""
    limit: int = Field(default=500, ge=0, le=MAX_PAGE_SIZE)


class ReviewStore:
    """Thread-safe, process-scoped review overlay with immutable IDs."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._created: dict[str, list[dict[str, Any]]] = {}
        self._patches: dict[str, dict[str, dict[str, Any]]] = {}

    def merge(self, entity_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self._lock:
            combined = [dict(row) for row in rows]
            combined.extend(dict(row) for row in self._created.get(entity_name, ()))
            patches = self._patches.get(entity_name, {})
            return [{**row, **patches.get(str(row.get("id")), {})} for row in combined]

    def create(
        self,
        entity_name: str,
        payload: dict[str, Any],
        reserved_ids: set[str],
    ) -> dict[str, Any]:
        with self._lock:
            existing = set(reserved_ids)
            existing.update(str(row.get("id")) for row in self._created.get(entity_name, ()))
            identifier = uuid.uuid4().hex
            while identifier in existing:
                identifier = uuid.uuid4().hex
            row = {**payload, "id": identifier, "_process_overlay": True}
            self._created.setdefault(entity_name, []).append(row)
            return dict(row)

    def patch(self, entity_name: str, entity_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._patches.setdefault(entity_name, {}).setdefault(entity_id, {}).update(payload)

    def clear(self) -> None:
        with self._lock:
            self._created.clear()
            self._patches.clear()


REVIEW_STORE = ReviewStore()


def require_write_access(request: Request) -> None:
    if not _WRITE_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Review-overlay writes are disabled. Set PRII_ENABLE_WRITES=true to enable them.",
        )
    if not _WRITE_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="PRII_ENABLE_WRITES is set but PRII_WRITE_TOKEN is not configured.",
        )
    scheme, _, presented = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(presented, _WRITE_TOKEN):
        raise HTTPException(status_code=401, detail="Missing or invalid write token")


_WRITE_GUARD = [Depends(require_write_access)]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Invalid JSON in {path.name} line {line_no}: {exc.msg}",
                ) from exc
            if isinstance(value, dict):
                rows.append(value)
    return rows


def coerce(value: str) -> Any:
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [
            {key: coerce(value) if isinstance(value, str) else value for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def _stable_id(row: dict[str, Any], key: str) -> str:
    existing = row.get(key)
    identity: Any = {key: existing} if existing not in (None, "") else row
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def with_id(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return [{**row, "id": row.get("id") or row.get(key) or _stable_id(row, key)} for row in rows]


@lru_cache(maxsize=1)
def load_airports() -> tuple[dict[str, Any], ...]:
    rows = with_id(read_jsonl(AIRPORTS_PATH), "airport_id")
    for row in rows:
        row.setdefault("airport_name", row.get("name"))
        row.setdefault("icao_code", row.get("icao"))
        row.setdefault("faa_code", row.get("iata"))
        row.setdefault("airport_type", row.get("landing_type"))
        row.setdefault("latitude", row.get("lat"))
        row.setdefault("longitude", row.get("lon"))
        row.setdefault("synthetic_flag", False)
    return tuple(rows)


@lru_cache(maxsize=1)
def load_observations() -> tuple[dict[str, Any], ...]:
    rows = with_id(read_csv(SYNTHETIC_PACKAGE / "observations.csv"), "observation_id")
    for row in rows:
        row.setdefault("synthetic_flag", row.get("synthetic"))
        row.setdefault("confidence_score", row.get("confidence"))
        row.setdefault("created_date", row.get("event_datetime"))
        row.setdefault("observed_at", row.get("event_datetime"))
        row.setdefault("latitude", row.get("lat"))
        row.setdefault("longitude", row.get("lon"))
    return tuple(rows)


@lru_cache(maxsize=1)
def load_export_packages() -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    if EXPORTS_DIR.exists():
        paths = sorted(EXPORTS_DIR.rglob("manifest.json")) + sorted(EXPORTS_DIR.rglob("summary.json"))
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                data.setdefault("path", str(path.parent.relative_to(ROOT)))
                if path.name == "summary.json":
                    data.setdefault("package_kind", "satim_calibration")
                rows.append(data)
    return tuple(with_id(rows, "package_id"))


@lru_cache(maxsize=1)
def load_readiness() -> tuple[dict[str, Any], ...]:
    return tuple(with_id(read_jsonl(EVIDENCE_PATH), "path"))


def clear_artifact_caches() -> None:
    for loader in (load_airports, load_observations, load_export_packages, load_readiness):
        loader.cache_clear()


LOADERS = {
    "PRAirports": load_airports,
    "AirspaceObservations": load_observations,
    "ExportPackages": load_export_packages,
    "ReadinessReports": load_readiness,
    "AircraftProfiles": tuple,
    "FR24Captures": tuple,
    "RouteSegments": tuple,
    "InfrastructureAssets": tuple,
    "AirspaceAssetLinks": tuple,
    "ManualReviewItems": tuple,
    "FederationSyncEvents": tuple,
}


def _loader_for(name: str):
    loader = LOADERS.get(name)
    if loader is None:
        raise HTTPException(status_code=404, detail=f"Unknown entity type: {name}")
    return loader


def entity_rows(name: str) -> list[dict[str, Any]]:
    return REVIEW_STORE.merge(name, [dict(row) for row in _loader_for(name)()])


def _sort_value(value: Any) -> tuple[int, int, Any]:
    if value is None or value == "":
        return (1, 0, "")
    if isinstance(value, bool):
        return (0, 0, int(value))
    if isinstance(value, (int, float)):
        return (0, 1, float(value))
    return (0, 2, str(value).casefold())


def sort_rows(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    if not sort:
        return rows
    reverse = sort.startswith("-")
    key = sort.lstrip("-")
    return sorted(rows, key=lambda row: _sort_value(row.get(key)), reverse=reverse)


@app.get("/health")
def health() -> dict[str, Any]:
    capabilities = {name: {"count": len(entity_rows(name))} for name in LOADERS}
    return {
        "status": "healthy" if capabilities["PRAirports"]["count"] else "degraded",
        "mode": "diagnostic_read_only" if not _WRITE_ENABLED else "diagnostic_review_overlay",
        "writes_enabled": _WRITE_ENABLED,
        "capabilities": capabilities,
        "counts": {name: value["count"] for name, value in capabilities.items()},
    }


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    return health()


@app.get("/api/apps/public-settings")
def public_settings() -> dict[str, Any]:
    return {
        "id": "skywatcher-pr",
        "name": "Skywatcher-PR — Airspace Evidence",
        "public_settings": {
            "requires_auth": False,
            "mode": "diagnostic",
            "review_overlay_writes": _WRITE_ENABLED and bool(_WRITE_TOKEN),
        },
    }


@app.get("/api/auth/me")
def auth_me() -> dict[str, Any]:
    raise HTTPException(status_code=401, detail="No auth in local diagnostic mode")


@app.get("/api/entities/{entity_name}")
def list_entities(
    entity_name: str,
    sort: str = Query("-created_date", max_length=128),
    limit: int = Query(500, ge=0, le=MAX_PAGE_SIZE),
) -> list[dict[str, Any]]:
    return sort_rows(entity_rows(entity_name), sort)[:limit]


@app.post("/api/entities/{entity_name}/filter")
def filter_entities(entity_name: str, payload: FilterRequest | None = None) -> list[dict[str, Any]]:
    request = payload or FilterRequest()
    rows = entity_rows(entity_name)
    for key, expected in request.filters.items():
        rows = [row for row in rows if row.get(key) == expected]
    return sort_rows(rows, request.sort)[: request.limit]


@app.get("/api/entities/{entity_name}/{entity_id}")
def get_entity(entity_name: str, entity_id: str) -> dict[str, Any]:
    for row in entity_rows(entity_name):
        if str(row.get("id")) == entity_id:
            return row
    raise HTTPException(status_code=404, detail=f"{entity_name} not found: {entity_id}")


@app.post("/api/entities/{entity_name}", dependencies=_WRITE_GUARD)
def create_entity(entity_name: str, payload: EntityPayload) -> dict[str, Any]:
    base = [dict(row) for row in _loader_for(entity_name)()]
    return REVIEW_STORE.create(
        entity_name,
        payload.root,
        {str(row.get("id")) for row in base},
    )


@app.patch("/api/entities/{entity_name}/{entity_id}", dependencies=_WRITE_GUARD)
def update_entity(entity_name: str, entity_id: str, payload: EntityPayload) -> dict[str, Any]:
    for row in entity_rows(entity_name):
        if str(row.get("id")) == entity_id:
            REVIEW_STORE.patch(entity_name, entity_id, payload.root)
            return {**row, **payload.root}
    raise HTTPException(status_code=404, detail=f"{entity_name} not found: {entity_id}")
