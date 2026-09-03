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
import ipaddress
import json
import logging
import os
import secrets
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from server.backend.console import router as console_router

ROOT = Path(__file__).resolve().parents[2]
# Make the src-layout package importable when uvicorn starts from the repo root.
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

AIRPORTS_PATH = ROOT / "data" / "reference" / "pr_airports.jsonl"
EXPORTS_DIR = ROOT / "exports"
SYNTHETIC_PACKAGE = EXPORTS_DIR / "examples" / "synthetic_airspace_package"
EVIDENCE_PATH = ROOT / "reports" / "federation" / "evidence_skywatcher-pr.jsonl"
CRAFT_PROFILE_DIR = ROOT / "profiles" / "craft"
RLSM_DB = ROOT / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
RLSM_MARKER_VERSION = "rlsm-aircraft-marker-v1"
RLSM_GEOREF_VERSION = "rlsm-spatial-georef-v1"
RLSM_MAX_POSITION_ERROR_M = 500

app = FastAPI(
    title="Skywatcher-PR Dashboard API",
    description="Read-only federation entity API over committed Skywatcher artifacts.",
    version="0.1.0",
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

log = logging.getLogger("skywatcher.backend")

# ── Write authorization ────────────────────────────────────────────────────────
# Diagnostic mode ships without authentication: /api/auth/me always 401s and
# public-settings reports requires_auth=false, so nothing else stands between a
# caller and the mutating routes. The overlay above is in-memory and never
# reaches disk, so the blast radius is one process — but every reader of this
# server still sees another client's unauthenticated edits until restart.
#
#   PRII_WRITE_TOKEN set    -> mutating routes require Authorization: Bearer <token>
#   PRII_WRITE_TOKEN unset  -> mutating routes are served to clients on a local
#                              network (loopback, RFC1918 private, link-local)
#                              and refused for public addresses
#
# The private-range allowance is deliberate: containerized or LAN deployments see
# a bridge address (typically 172.17.0.1) rather than 127.0.0.1, and a strict
# loopback-only rule would 403 every write from the shipped UI in those setups.
# Refusing public addresses still closes the case this is meant to close.
#
# Caveat when the token IS set: the browser UI has no write-credential input
# (federationClient sources only the federation access token, and AuthContext
# drops that when /api/auth/me 401s), so token mode currently suits API/CLI
# callers rather than the shipped UI. Tracked in docs/MATURITY_AUDIT.md.
#
# Reads are unaffected in every case.
_WRITE_TOKEN = os.environ.get("PRII_WRITE_TOKEN", "")


def _is_local_network(host: str) -> bool:
    """True for loopback, RFC1918 private, and link-local client addresses."""
    if host in ("localhost", ""):
        return host == "localhost"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def require_write_access(request: Request) -> None:
    """Authorize a mutating request, by bearer token or by local-network origin."""
    if _WRITE_TOKEN:
        scheme, _, presented = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(presented, _WRITE_TOKEN):
            raise HTTPException(status_code=401, detail="Missing or invalid write token")
        return

    if not _is_local_network(request.client.host if request.client else ""):
        raise HTTPException(
            status_code=403,
            detail=(
                "Writes from public addresses are refused while PRII_WRITE_TOKEN "
                "is unset. Set it to enable authenticated writes from anywhere."
            ),
        )


_WRITE_GUARD = [Depends(require_write_access)]

if not _WRITE_TOKEN:
    log.warning(
        "PRII_WRITE_TOKEN is unset — mutating /api routes accept any client on "
        "a local network and are refused for public addresses. Set the token "
        "before exposing this server beyond a trusted network."
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
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
            {key: coerce(value) if isinstance(value, str) else value for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def with_id(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    for row in rows:
        row.setdefault("id", row.get(key) or uuid.uuid4().hex)
    return rows


def load_airports() -> list[dict[str, Any]]:
    rows = with_id(read_jsonl(AIRPORTS_PATH), "airport_id")
    # The registry schema names differ from the dashboard's native fields;
    # alias without dropping the originals.
    for row in rows:
        row.setdefault("airport_name", row.get("name"))
        row.setdefault("icao_code", row.get("icao"))
        row.setdefault("faa_code", row.get("iata"))
        row.setdefault("airport_type", row.get("landing_type"))
        row.setdefault("latitude", row.get("lat"))
        row.setdefault("longitude", row.get("lon"))
        row.setdefault("synthetic_flag", False)
    return rows


def _rlsm_rows(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Query an operator-local RLSM database without creating or mutating it."""
    if not RLSM_DB.is_file():
        return []
    uri = f"{RLSM_DB.resolve().as_uri()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(query, params).fetchall()]
    except sqlite3.Error as exc:
        # A checkout without the spatial migration remains a valid diagnostic
        # deployment.  It advertises zero spatial rows until the pipeline runs.
        log.warning("RLSM spatial entity unavailable: %s", exc)
        return []


def load_rlsm_spatial_observations() -> list[dict[str, Any]]:
    rows = _rlsm_rows(
        """SELECT a.aircraft_obs_id, a.registration, a.callsign,
                  a.aircraft_type, a.altitude_ft, a.speed_kt, a.heading_deg,
                  a.operator_text, a.confidence, a.pixel_x, a.pixel_y,
                  a.icon_rotation_deg, a.marker_confidence, a.marker_method,
                  a.position_lat, a.position_lon, a.position_method,
                  a.position_confidence, a.position_error_m,
                  a.position_observed_at, a.observed_at,
                  s.screenshot_id, s.filename, s.filename_ts
           FROM aircraft_observations a
           JOIN screenshots s USING(screenshot_id)
           JOIN aircraft_marker_frames f
             ON f.screenshot_id = a.screenshot_id
            AND f.detector_version = a.marker_method
            AND f.status = 'selected'
           JOIN aircraft_marker_detections d
             ON d.marker_frame_id = f.marker_frame_id
            AND d.aircraft_obs_id = a.aircraft_obs_id
            AND d.selected = 1
           JOIN screenshot_georeferences g
             ON g.screenshot_id = a.screenshot_id
            AND g.georef_version = ?
            AND g.status = 'located'
            AND g.method = a.position_method
           WHERE a.position_lat IS NOT NULL AND a.position_lon IS NOT NULL
             AND a.marker_method = ?
             AND a.position_method IN (
                 'multi_anchor_affine', 'one_anchor_zoom_rung'
             )
             AND a.position_error_m IS NOT NULL AND a.position_error_m <= ?
             AND g.estimated_error_m IS NOT NULL
             AND g.estimated_error_m <= ?
           ORDER BY COALESCE(s.filename_ts, a.observed_at) DESC,
                    a.aircraft_obs_id DESC""",
        (
            RLSM_GEOREF_VERSION,
            RLSM_MARKER_VERSION,
            RLSM_MAX_POSITION_ERROR_M,
            RLSM_MAX_POSITION_ERROR_M,
        ),
    )
    observations: list[dict[str, Any]] = []
    for row in rows:
        observed_at = row.get("filename_ts") or row.get("observed_at")
        observations.append(
            {
                "id": f"rlsm-aircraft-{row['aircraft_obs_id']}",
                "observation_id": f"rlsm-aircraft-{row['aircraft_obs_id']}",
                "aircraft_obs_id": row["aircraft_obs_id"],
                "tail_number": row.get("registration"),
                "registration": row.get("registration"),
                "callsign": row.get("callsign"),
                "aircraft_type": row.get("aircraft_type"),
                "altitude_ft": row.get("altitude_ft"),
                "speed_kt": row.get("speed_kt"),
                # OCR/PCA heading is retained as metadata and is never replaced
                # with the independently measured icon rotation.
                "heading_deg": row.get("heading_deg"),
                "icon_rotation_deg": row.get("icon_rotation_deg"),
                "operator_name": row.get("operator_text"),
                "latitude": row.get("position_lat"),
                "longitude": row.get("position_lon"),
                "pixel_x": row.get("pixel_x"),
                "pixel_y": row.get("pixel_y"),
                "marker_method": row.get("marker_method"),
                "marker_confidence": row.get("marker_confidence"),
                "position_method": row.get("position_method"),
                "position_confidence": row.get("position_confidence"),
                "position_error_m": row.get("position_error_m"),
                "position_observed_at": row.get("position_observed_at"),
                "confidence_score": row.get("position_confidence"),
                "source_type": "fr24_screenshot",
                "source_screenshot_id": row.get("screenshot_id"),
                "source_filename": row.get("filename"),
                "linked_capture_id": f"rlsm-frame-{row['screenshot_id']}",
                "observed_at": observed_at,
                "created_date": observed_at,
                "review_status": "new",
                "synthetic": False,
                "synthetic_flag": False,
            }
        )
    return observations


def load_observations() -> list[dict[str, Any]]:
    rows = with_id(read_csv(SYNTHETIC_PACKAGE / "observations.csv"), "observation_id")
    # The export package schema names differ from the dashboard's native
    # fields; alias without dropping the originals.
    for row in rows:
        row.setdefault("synthetic_flag", row.get("synthetic"))
        row.setdefault("confidence_score", row.get("confidence"))
        row.setdefault("created_date", row.get("event_datetime"))
        row.setdefault("observed_at", row.get("event_datetime"))
        row.setdefault("latitude", row.get("lat"))
        row.setdefault("longitude", row.get("lon"))
    return rows + load_rlsm_spatial_observations()


def load_rlsm_aircraft_profiles() -> list[dict[str, Any]]:
    """Expose one lightweight profile for each spatially located registration."""
    profiles: dict[str, dict[str, Any]] = {}
    for row in load_rlsm_spatial_observations():
        registration = row.get("registration")
        if not registration:
            continue
        profile = profiles.setdefault(
            str(registration),
            {
                "id": f"rlsm-profile-{registration}",
                "aircraft_id": f"rlsm-profile-{registration}",
                "tail_number": registration,
                "registration": registration,
                "aircraft_type": row.get("aircraft_type"),
                "operator_name": row.get("operator_name"),
                "source_type": "fr24_screenshot",
                "synthetic_flag": False,
                "observation_count": 0,
                "latest_observed_at": row.get("observed_at"),
            },
        )
        profile["observation_count"] += 1
        if str(row.get("observed_at") or "") > str(profile.get("latest_observed_at") or ""):
            profile["latest_observed_at"] = row.get("observed_at")
    return sorted(profiles.values(), key=lambda row: str(row["tail_number"]))


def load_craft_profiles() -> list[dict[str, Any]]:
    """Load whole committed craft-profile rows without inferring mission fields."""
    rows: list[dict[str, Any]] = []
    if not CRAFT_PROFILE_DIR.exists():
        return rows
    for path in sorted(CRAFT_PROFILE_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict) or not data.get("registration"):
            continue
        mission = data.get("primary_mission") if data.get("mission_is_authoritative") else None
        data.setdefault("id", data["registration"])
        data.setdefault("aircraft_id", data["registration"])
        data.setdefault("tail_number", data["registration"])
        data.setdefault("operator_category", data.get("operator"))
        data.setdefault("mission_category", mission)
        data.setdefault("profile_confidence", data.get("confidence_level"))
        data.setdefault("synthetic_flag", False)
        data.setdefault("last_seen_at", data.get("last_seen"))
        data.setdefault("observation_count", data.get("total_observations"))
        data.setdefault("registry_source", data.get("data_source"))
        rows.append(data)
    return rows


def load_aircraft_profiles() -> list[dict[str, Any]]:
    """Select one whole profile per stable registration.

    A committed craft profile supersedes the lightweight RLSM row for the same
    registration; unmatched rows from either source remain visible.
    """
    profiles = {
        str(row["registration"]): row
        for row in load_rlsm_aircraft_profiles()
        if row.get("registration")
    }
    for row in load_craft_profiles():
        profiles[str(row["registration"])] = row
    return [profiles[key] for key in sorted(profiles)]


def load_rlsm_spatial_frames() -> list[dict[str, Any]]:
    rows = _rlsm_rows(
        """SELECT s.screenshot_id, s.filename, s.filename_ts,
                  f.detector_version, f.status AS marker_status,
                  f.candidate_count, f.selected_candidate_rank,
                  f.reason AS marker_reason, f.observed_at AS marker_observed_at,
                  g.georef_version, g.status AS georef_status,
                  g.method AS georef_method, g.anchor_count, g.viewport_profile,
                  g.scale_m_per_px, g.zoom_rung, g.zoom_support,
                  g.confidence AS georef_confidence,
                  g.estimated_error_m
           FROM screenshots s
           LEFT JOIN aircraft_marker_frames f
             ON f.screenshot_id = s.screenshot_id
            AND f.detector_version = ?
           LEFT JOIN screenshot_georeferences g
             ON g.screenshot_id = s.screenshot_id
            AND g.georef_version = ?
           WHERE EXISTS (
               SELECT 1 FROM aircraft_observations a
               WHERE a.screenshot_id=s.screenshot_id
           )
           ORDER BY COALESCE(s.filename_ts, f.observed_at, g.observed_at) DESC,
                    s.screenshot_id DESC""",
        (RLSM_MARKER_VERSION, RLSM_GEOREF_VERSION),
    )
    for row in rows:
        row["id"] = f"rlsm-frame-{row['screenshot_id']}"
        row["capture_id"] = row["id"]
        row["created_date"] = row.get("filename_ts") or row.get("marker_observed_at")
    return rows


def load_rlsm_zoom_rungs() -> list[dict[str, Any]]:
    rows = _rlsm_rows(
        """SELECT georef_version, viewport_profile, zoom_rung,
                  scale_m_per_px, dlon_dx, dlat_dy, support_count,
                  dispersion_log2, eligible_for_transfer, evidence_json,
                  observed_at
           FROM zoom_ladder_rungs
           WHERE georef_version = ?
           ORDER BY viewport_profile, zoom_rung""",
        (RLSM_GEOREF_VERSION,),
    )
    for row in rows:
        row["id"] = f"{row['georef_version']}:{row['viewport_profile']}:{row['zoom_rung']}"
        row["created_date"] = row.get("observed_at")
        row["eligible_for_transfer"] = bool(row.get("eligible_for_transfer"))
    return rows


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
    return with_id(rows, "package_id")


def load_readiness() -> list[dict[str, Any]]:
    return with_id(read_jsonl(EVIDENCE_PATH), "path")


def _lens_registries():
    """Load the committed analysis registries, or None when they are unavailable.

    Returns None rather than raising: this backend is a read-only diagnostic surface
    over committed artifacts, and a malformed lens file should degrade one panel rather
    than take the whole dashboard down. The ontology gate is what fails closed on a bad
    registry; this is the viewer.
    """
    try:
        from skywatcher.core.lenses import load_default_registries

        return load_default_registries()
    except Exception:  # noqa: BLE001 - any load failure degrades to an empty panel
        log.warning("analysis lens registry unavailable", exc_info=True)
        return None


def load_analysis_lenses() -> list[dict[str, Any]]:
    registries = _lens_registries()
    if registries is None:
        return []
    lenses, _ = registries
    rows = []
    for lens in lenses.all():
        row = lens.to_dict()
        # Flattened counts so the table can sort without unpacking nested lists.
        row["required_parameter_count"] = len(lens.required_parameters)
        row["optional_parameter_count"] = len(lens.optional_parameters)
        row["threshold_count"] = len(lens.threshold_ids)
        rows.append(row)
    return with_id(rows, "lens_id")


def load_analysis_objectives() -> list[dict[str, Any]]:
    registries = _lens_registries()
    if registries is None:
        return []
    _, objectives = registries
    rows = []
    for profile in objectives.all():
        row = profile.to_dict()
        row["required_lens_count"] = len(profile.required_lenses)
        row["optional_lens_count"] = len(profile.optional_lenses)
        rows.append(row)
    return with_id(rows, "profile_id")


def load_lens_coverage() -> list[dict[str, Any]]:
    """Committed coverage reports emitted by pipeline runs.

    Empty until a run writes one, matching how the other pipeline-fed entities behave.
    """
    rows: list[dict[str, Any]] = []
    for path in sorted(ROOT.glob("reports/**/coverage_report.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            data.setdefault("path", str(path.parent.relative_to(ROOT)))
            rows.append(data)
    return with_id(rows, "run_id")


LOADERS = {
    "PRAirports": load_airports,
    "AirspaceObservations": load_observations,
    "ExportPackages": load_export_packages,
    "ReadinessReports": load_readiness,
    "AnalysisLenses": load_analysis_lenses,
    "AnalysisObjectives": load_analysis_objectives,
    "LensCoverage": load_lens_coverage,
    # Declared by the dashboard but with no committed source yet; empty until
    # the corresponding pipelines emit repo artifacts.
    "AircraftProfiles": load_aircraft_profiles,
    "RLSMSpatialObservations": load_rlsm_spatial_observations,
    "RLSMSpatialFrames": load_rlsm_spatial_frames,
    "RLSMZoomRungs": load_rlsm_zoom_rungs,
    "FR24Captures": list,
    "RouteSegments": list,
    "InfrastructureAssets": list,
    "AirspaceAssetLinks": list,
    "ManualReviewItems": list,
    "FederationSyncEvents": list,
}


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
        # write_token_required lets the UI distinguish "this server wants a bearer
        # token on writes" from "this server accepts writes from my network". The
        # browser cannot read PRII_WRITE_TOKEN, so without this both look identical
        # until a write 401s. Only the boolean is exposed, never the token.
        "public_settings": {
            "requires_auth": False,
            "mode": "diagnostic",
            "write_token_required": bool(_WRITE_TOKEN),
        },
    }


@app.get("/api/analysis/registry")
def analysis_registry() -> dict[str, Any]:
    """Serve the lens, objective, and threshold registries to the GUI.

    Exists so the dashboard stops hardcoding analytical vocabulary. Every other
    vocabulary in the frontend is a literal in JSX that has to be updated by hand when
    the backend changes; this one is fetched, so adding a lens reaches the UI with no
    frontend edit. tests/test_analysis_registry_gui_parity.py pins that agreement.
    """
    registries = _lens_registries()
    if registries is None:
        return {"available": False, "lenses": [], "objectives": [], "thresholds": []}

    lenses, objectives = registries
    payload: dict[str, Any] = {
        "available": True,
        "lenses": [lens.to_dict() for lens in lenses.all()],
        "objectives": [profile.to_dict() for profile in objectives.all()],
        "stages": sorted({lens.stage for lens in lenses.all()}),
        "owners": sorted({lens.owner for lens in lenses.all()}),
    }

    try:
        from skywatcher.core.lenses import ThresholdRegistry

        thresholds = ThresholdRegistry()
        thresholds.load()
        payload["thresholds"] = thresholds.to_dict()["thresholds"]
    except Exception:  # noqa: BLE001 - thresholds are a panel, not the whole page
        log.warning("threshold registry unavailable", exc_info=True)
        payload["thresholds"] = []

    return payload


@app.get("/api/auth/me")
def auth_me() -> dict[str, Any]:
    raise HTTPException(status_code=401, detail="No auth in local diagnostic mode")


@app.post("/api/query")
def query(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Answer only from persisted craft profiles, with deterministic fallback."""
    payload = payload or {}
    prompt = str(payload.get("prompt") or payload.get("q") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Missing 'prompt'")

    try:
        from skywatcher.query.engine import QueryEngine
    except ImportError as exc:  # pragma: no cover - import wiring
        raise HTTPException(status_code=500, detail=f"query engine unavailable: {exc}") from exc

    engine = QueryEngine(db_path=RLSM_DB, profile_dir=CRAFT_PROFILE_DIR)
    answer = engine.answer(prompt)
    result = answer.to_dict()
    if payload.get("natural_language"):
        from skywatcher.query.llm import ask

        result["text"] = ask(prompt, engine=engine)
    else:
        result["text"] = answer.to_text()
    return result


@app.get("/api/entities/{entity_name}")
def list_entities(
    entity_name: str,
    sort: str = Query("-created_date"),
    limit: int = Query(500),
) -> list[dict[str, Any]]:
    return sort_rows(entity_rows(entity_name), sort)[: max(limit, 0)]


@app.post("/api/entities/{entity_name}/filter")
def filter_entities(
    entity_name: str, payload: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    payload = payload or {}
    filters = payload.get("filters") or {}
    rows = entity_rows(entity_name)
    for key, expected in filters.items():
        rows = [row for row in rows if row.get(key) == expected]
    limit = int(payload.get("limit") or 500)
    return sort_rows(rows, str(payload.get("sort") or ""))[: max(limit, 0)]


@app.get("/api/entities/{entity_name}/{entity_id}")
def get_entity(entity_name: str, entity_id: str) -> dict[str, Any]:
    for row in entity_rows(entity_name):
        if str(row.get("id")) == entity_id:
            return row
    raise HTTPException(status_code=404, detail=f"{entity_name} not found: {entity_id}")


@app.post("/api/entities/{entity_name}", dependencies=_WRITE_GUARD)
def create_entity(entity_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    row = dict(payload)
    row.setdefault("id", uuid.uuid4().hex)
    row.setdefault("_session_only", True)
    _created.setdefault(entity_name, []).append(row)
    return row


@app.patch("/api/entities/{entity_name}/{entity_id}", dependencies=_WRITE_GUARD)
def update_entity(entity_name: str, entity_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    for row in entity_rows(entity_name):
        if str(row.get("id")) == entity_id:
            _overlay.setdefault(entity_name, {}).setdefault(entity_id, {}).update(payload)
            return {**row, **payload}
    raise HTTPException(status_code=404, detail=f"{entity_name} not found: {entity_id}")
