"""Read-only FastAPI backend for the Skywatcher-PR dashboard.

Implements the PRII federation entity contract (/api/entities/{name} +
/api/apps/public-settings + /api/auth/me) over the artifacts committed in
this repository — airport registry, the synthetic airspace export package,
SATIM calibration summaries, and the federation evidence ledger. The repo
files are never mutated: entity updates/creates from the review UI are kept
in a session-scoped in-memory overlay that disappears on restart.

Start with:
    python -m uvicorn server.backend.main:app --port 8000
(from the skywatcher-pr repo root, with fastapi/uvicorn installed)
"""

from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from server.backend.console import router as console_router
from server.backend.console.repositories import RepositoryRegistry, row_has_complete_provenance
from server.backend.console.repositories.normalize import attach_provenance
from server.backend.console.source_taxonomy import build_provenance, normalize_observation

ROOT = Path(__file__).resolve().parents[2]
AIRPORTS_PATH = ROOT / "data" / "reference" / "pr_airports.jsonl"
EXPORTS_DIR = ROOT / "exports"
SYNTHETIC_PACKAGE = EXPORTS_DIR / "examples" / "synthetic_airspace_package"
EVIDENCE_PATH = ROOT / "reports" / "federation" / "evidence_skywatcher-pr.jsonl"

app = FastAPI(
    title="Skywatcher-PR Dashboard API",
    description="Read-only federation entity API over committed Skywatcher artifacts.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(console_router)

# Session-scoped mutations from the review UI; never written to disk.
_overlay: dict[str, dict[str, dict[str, Any]]] = {}
_created: dict[str, list[dict[str, Any]]] = {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Invalid JSON in {path.relative_to(ROOT)} line {line_no}: {exc.msg}",
            ) from exc
        if isinstance(value, dict):
            rows.append(value)
    return rows


def coerce(value: str) -> Any:
    """Give CSV strings their natural JSON types (bool/int/float)."""
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
            {
                key: coerce(value) if isinstance(value, str) else value
                for key, value in row.items()
            }
            for row in csv.DictReader(handle)
        ]


def with_id(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    for row in rows:
        row.setdefault("id", row.get(key) or uuid.uuid4().hex)
    return rows


def load_airports() -> list[dict[str, Any]]:
    rows = with_id(read_jsonl(AIRPORTS_PATH), "airport_id")
    output: list[dict[str, Any]] = []
    for row in rows:
        row.setdefault("airport_name", row.get("name"))
        row.setdefault("icao_code", row.get("icao"))
        row.setdefault("faa_code", row.get("iata"))
        row.setdefault("airport_type", row.get("landing_type"))
        row.setdefault("latitude", row.get("lat"))
        row.setdefault("longitude", row.get("lon"))
        row.setdefault("synthetic_flag", False)
        source_id = str(row.get("airport_id") or row.get("id"))
        output.append(attach_provenance(
            row,
            path=AIRPORTS_PATH,
            adapter="dashboard:PRAirports",
            source_record_id=source_id,
            source_family="official_record",
            source_provider="skywatcher-pr-airport-registry",
            source_method="official_feed",
            data_rights="derived",
            operational_mode="batch",
            artifact_kind="airport_registry",
            synthetic=False,
        ))
    return output


def load_observations() -> list[dict[str, Any]]:
    observation_path = SYNTHETIC_PACKAGE / "observations.csv"
    rows = with_id(read_csv(observation_path), "observation_id")
    output: list[dict[str, Any]] = []
    for row in rows:
        row.setdefault("synthetic_flag", row.get("synthetic"))
        row.setdefault("confidence_score", row.get("confidence"))
        row.setdefault("created_date", row.get("event_datetime"))
        row.setdefault("observed_at", row.get("event_datetime"))
        row.setdefault("latitude", row.get("lat"))
        row.setdefault("longitude", row.get("lon"))
        row["synthetic"] = bool(row.get("synthetic") or row.get("synthetic_flag"))
        row["artifact_path"] = str(observation_path)
        row["artifact_sha256"] = None
        row["ingest_adapter"] = "dashboard:AirspaceObservations"
        row = normalize_observation(row)
        provenance, qa_flags = build_provenance(row)
        row["provenance"] = provenance
        row["qa_flags"] = sorted(set(list(row.get("qa_flags") or []) + qa_flags))
        output.append(row)
    return output


def load_export_packages() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if EXPORTS_DIR.exists():
        for manifest in sorted(EXPORTS_DIR.rglob("manifest.json")):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                data.setdefault("path", str(manifest.parent.relative_to(ROOT)))
                rows.append(data)
        for summary in sorted(EXPORTS_DIR.rglob("summary.json")):
            try:
                data = json.loads(summary.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                data.setdefault("path", str(summary.parent.relative_to(ROOT)))
                data.setdefault("package_kind", "satim_calibration")
                rows.append(data)
    rows = with_id(rows, "package_id")
    output: list[dict[str, Any]] = []
    for row in rows:
        source_id = str(row.get("package_id") or row.get("id"))
        path_value = ROOT / str(row.get("path") or "exports")
        output.append(attach_provenance(
            row,
            path=path_value,
            adapter="dashboard:ExportPackages",
            source_record_id=source_id,
            source_family="secondary_reference",
            source_provider="skywatcher-export-pipeline",
            source_method="derived_fusion",
            data_rights="derived",
            operational_mode="batch",
            artifact_kind="export_package",
            synthetic=bool(row.get("synthetic")),
        ))
    return output


def load_readiness() -> list[dict[str, Any]]:
    rows = with_id(read_jsonl(EVIDENCE_PATH), "path")
    return [
        attach_provenance(
            row,
            path=EVIDENCE_PATH,
            adapter="dashboard:ReadinessReports",
            source_record_id=str(row.get("id") or row.get("path")),
            source_family="secondary_reference",
            source_provider="skywatcher-readiness-engine",
            source_method="secondary_report",
            data_rights="derived",
            operational_mode="batch",
            artifact_kind="readiness_report",
            synthetic=bool(row.get("synthetic")),
        )
        for row in rows
    ]


def load_repository_entity(repository_name: str) -> list[dict[str, Any]]:
    return RepositoryRegistry(ROOT).snapshot(repository_name).rows


LOADERS = {
    "PRAirports": load_airports,
    "AirspaceObservations": load_observations,
    "ExportPackages": load_export_packages,
    "ReadinessReports": load_readiness,
    "AircraftProfiles": lambda: load_repository_entity("aircraft_profiles"),
    "FR24Captures": lambda: load_repository_entity("fr24_captures"),
    "RouteSegments": lambda: load_repository_entity("route_segments"),
    "ManualReviewItems": lambda: load_repository_entity("manual_review_items"),
    "InfrastructureAssets": list,
    "AirspaceAssetLinks": list,
    "FederationSyncEvents": list,
}

STATIC_EMPTY_REASONS = {
    "InfrastructureAssets": "No infrastructure-asset artifact is connected in Phase 2.",
    "AirspaceAssetLinks": "No airspace-asset link artifact is connected in Phase 2.",
    "FederationSyncEvents": "No federation-sync event artifact is connected in Phase 2.",
}


def entity_availability(name: str) -> dict[str, Any]:
    snapshot = RepositoryRegistry(ROOT).entity_snapshot(name)
    if snapshot is not None:
        return snapshot.as_status()
    loader = LOADERS.get(name)
    if loader is None:
        return {
            "repository": name,
            "status": "unavailable_no_adapter",
            "reason": "No entity loader or Phase 2 repository adapter is registered.",
            "record_count": 0,
            "synthetic_only": False,
            "provenance_complete": True,
            "warnings": [],
            "artifacts": [],
        }
    rows = loader()
    return {
        "repository": name,
        "status": "available" if rows else "unavailable_no_artifact",
        "reason": (
            "Entity loader returned provenance-backed rows."
            if rows
            else STATIC_EMPTY_REASONS.get(name, "The configured entity artifact is absent or empty.")
        ),
        "record_count": len(rows),
        "synthetic_only": bool(rows) and all(bool(row.get("synthetic") or row.get("synthetic_flag")) for row in rows),
        "provenance_complete": all(row_has_complete_provenance(row) for row in rows),
        "warnings": [],
        "artifacts": [],
    }


def set_availability_headers(response: Response, availability: dict[str, Any]) -> None:
    response.headers["X-Skywatcher-Availability"] = str(availability.get("status") or "unknown")
    response.headers["X-Skywatcher-Record-Count"] = str(availability.get("record_count") or 0)
    response.headers["X-Skywatcher-Provenance-Complete"] = str(bool(availability.get("provenance_complete"))).lower()
    reason = str(availability.get("reason") or "").replace("\n", " ")
    response.headers["X-Skywatcher-Availability-Reason"] = reason[:512]


def entity_rows(name: str) -> list[dict[str, Any]]:
    loader = LOADERS.get(name)
    rows = loader() if loader else []
    rows = rows + list(_created.get(name, []))
    patches = _overlay.get(name, {})
    if patches:
        rows = [{**row, **patches.get(str(row.get("id")), {})} for row in rows]
    return rows


def sort_rows(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    if not sort:
        return rows
    reverse = sort.startswith("-")
    key = sort.lstrip("-")
    return sorted(rows, key=lambda row: str(row.get(key) or ""), reverse=reverse)


@app.get("/health")
def health() -> dict[str, Any]:
    counts = {name: len(entity_rows(name)) for name in LOADERS}
    return {"status": "ok", "mode": "read_only_diagnostic", "counts": counts}


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    return health()


@app.get("/api/apps/public-settings")
def public_settings() -> dict[str, Any]:
    return {
        "id": "skywatcher-pr",
        "name": "Skywatcher-PR — Airspace Intelligence",
        "public_settings": {"requires_auth": False, "mode": "diagnostic"},
    }


@app.get("/api/auth/me")
def auth_me() -> dict[str, Any]:
    raise HTTPException(status_code=401, detail="No auth in local diagnostic mode")


@app.get("/api/entities/{entity_name}")
def list_entities(
    entity_name: str,
    response: Response,
    sort: str = Query("-created_date"),
    limit: int = Query(500),
) -> list[dict[str, Any]]:
    availability = entity_availability(entity_name)
    set_availability_headers(response, availability)
    return sort_rows(entity_rows(entity_name), sort)[: max(limit, 0)]


@app.post("/api/entities/{entity_name}/filter")
def filter_entities(
    entity_name: str, response: Response, payload: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    availability = entity_availability(entity_name)
    set_availability_headers(response, availability)
    payload = payload or {}
    filters = payload.get("filters") or {}
    rows = entity_rows(entity_name)
    for key, expected in filters.items():
        rows = [row for row in rows if row.get(key) == expected]
    limit = int(payload.get("limit") or 500)
    return sort_rows(rows, str(payload.get("sort") or ""))[: max(limit, 0)]


@app.get("/api/entities/{entity_name}/availability")
def get_entity_availability(entity_name: str) -> dict[str, Any]:
    return entity_availability(entity_name)


@app.get("/api/entities/{entity_name}/{entity_id}")
def get_entity(entity_name: str, entity_id: str) -> dict[str, Any]:
    for row in entity_rows(entity_name):
        if str(row.get("id")) == entity_id:
            return row
    raise HTTPException(status_code=404, detail=f"{entity_name} not found: {entity_id}")


@app.post("/api/entities/{entity_name}")
def create_entity(entity_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    row = dict(payload)
    row.setdefault("id", uuid.uuid4().hex)
    row.setdefault("_session_only", True)
    if not row_has_complete_provenance(row):
        row = attach_provenance(
            row,
            path=ROOT / ".diagnostic_session_overlay",
            adapter="dashboard:session_overlay",
            source_record_id=str(row["id"]),
            source_family="manual_field",
            source_provider="skywatcher-diagnostic-session",
            source_method="manual_entry",
            data_rights="user_supplied",
            operational_mode="batch",
            artifact_kind="session_overlay",
            synthetic=bool(row.get("synthetic")),
        )
    _created.setdefault(entity_name, []).append(row)
    return row


@app.patch("/api/entities/{entity_name}/{entity_id}")
def update_entity(
    entity_name: str, entity_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    for row in entity_rows(entity_name):
        if str(row.get("id")) == entity_id:
            _overlay.setdefault(entity_name, {}).setdefault(entity_id, {}).update(
                payload
            )
            return {**row, **payload}
    raise HTTPException(status_code=404, detail=f"{entity_name} not found: {entity_id}")
