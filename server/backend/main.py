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
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from server.backend.console import router as console_router
from server.backend.console.repositories import RepositoryRegistry, row_has_complete_provenance
from server.backend.console.repositories.normalize import attach_provenance
from server.backend.console.source_taxonomy import build_provenance, normalize_observation

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
ADSB_DB = Path(os.environ["SKYWATCHER_DB"]) if os.environ.get("SKYWATCHER_DB") else ROOT / "data" / "skywatcher.db"
# Committed as .json rather than .geojson: this repo's .gitignore blanket-excludes
# *.geojson (data-policy convention for generated/runtime export artifacts), but
# this is checked-in reference boundary data, the same file already committed by
# aguayluz-pr and ovnis-pr under the identical name→GEOID shape.
MUNICIPIOS_PATH = ROOT / "data" / "geo" / "pr_municipios_boundaries.json"

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

log = logging.getLogger("skywatcher.backend")

# The root-level gis_intelligence.py shim bootstraps src/ onto sys.path itself
# (see docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md); importing it here rather than
# reaching into skywatcher.corrim.gis_intelligence directly keeps this file on
# the one supported cross-boundary entry point. Guarded: src/skywatcher is an
# implicit namespace package (no __init__.py), which the frozen PyInstaller
# desktop build's static import analysis does not follow through this
# runtime sys.path.insert — so this import can legitimately fail there. Rather
# than crash the whole app on startup, degrade the way _rlsm_rows already does
# for a checkout without its optional data: the infrastructure/corridor/
# heatmap geo endpoints report empty until this module is available.
try:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from gis_intelligence import (
        CorridorAnalyzer,
        HeatmapGenerator,
        PuertoRicoInfrastructure,
    )
except ImportError as exc:
    log.warning("gis_intelligence unavailable (%s); infrastructure/corridor/heatmap geo endpoints will report empty.", exc)
    CorridorAnalyzer = HeatmapGenerator = PuertoRicoInfrastructure = None

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
    return output + load_rlsm_spatial_observations()


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
    "AircraftProfiles": load_aircraft_profiles,
    "RLSMSpatialObservations": load_rlsm_spatial_observations,
    "RLSMSpatialFrames": load_rlsm_spatial_frames,
    "RLSMZoomRungs": load_rlsm_zoom_rungs,
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


@app.post("/api/entities/{entity_name}", dependencies=_WRITE_GUARD)
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


@app.patch("/api/entities/{entity_name}/{entity_id}", dependencies=_WRITE_GUARD)
def update_entity(entity_name: str, entity_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    for row in entity_rows(entity_name):
        if str(row.get("id")) == entity_id:
            _overlay.setdefault(entity_name, {}).setdefault(entity_id, {}).update(payload)
            return {**row, **payload}
    raise HTTPException(status_code=404, detail=f"{entity_name} not found: {entity_id}")


# ============================================================================
# GIS / geo endpoints
#
# These serve real GeoJSON geometry to the MapLibre-based frontend, replacing
# the earlier hand-rolled SVG projection. Infrastructure zones and flight
# corridors are buffered into real Polygon geometry server-side (haversine
# destination-point sampling) rather than shipping lat/lon+radius for the
# client to approximate. All pure GET, computed in-memory — no repo files
# are written, matching this module's read-only diagnostic contract.
# ============================================================================

_EARTH_RADIUS_NM = 3440.065


def _destination_point(lat: float, lon: float, bearing_deg: float, distance_nm: float) -> tuple[float, float]:
    """Great-circle destination point given a start point, bearing, and distance."""
    from math import asin, atan2, cos, degrees, radians, sin

    d_r = distance_nm / _EARTH_RADIUS_NM
    br = radians(bearing_deg)
    lat1 = radians(lat)
    lon1 = radians(lon)
    lat2 = asin(sin(lat1) * cos(d_r) + cos(lat1) * sin(d_r) * cos(br))
    lon2 = lon1 + atan2(sin(br) * sin(d_r) * cos(lat1), cos(d_r) - sin(lat1) * sin(lat2))
    return degrees(lat2), degrees(lon2)


def _initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import atan2, cos, degrees, radians, sin

    lat1r, lat2r = radians(lat1), radians(lat2)
    dlon = radians(lon2 - lon1)
    x = sin(dlon) * cos(lat2r)
    y = cos(lat1r) * sin(lat2r) - sin(lat1r) * cos(lat2r) * cos(dlon)
    return (degrees(atan2(x, y)) + 360) % 360


def _circle_polygon(lat: float, lon: float, radius_nm: float, n: int = 32) -> dict[str, Any]:
    """Approximate a circular buffer (e.g. a restricted-airspace radius) as an
    n-gon GeoJSON Polygon, rather than shipping the raw radius to the client.
    """
    ring = []
    for i in range(n):
        bearing = (360.0 / n) * i
        plat, plon = _destination_point(lat, lon, bearing, radius_nm)
        ring.append([plon, plat])
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def _corridor_polygon(
    start: tuple[float, float], end: tuple[float, float], width_nm: float
) -> dict[str, Any]:
    """Buffer a start->end corridor centerline into a rectangular GeoJSON
    Polygon of the given width, via perpendicular offsets at each endpoint.
    """
    lat1, lon1 = start
    lat2, lon2 = end
    bearing = _initial_bearing(lat1, lon1, lat2, lon2)
    half_w = width_nm / 2
    p1 = _destination_point(lat1, lon1, bearing - 90, half_w)
    p2 = _destination_point(lat2, lon2, bearing - 90, half_w)
    p3 = _destination_point(lat2, lon2, bearing + 90, half_w)
    p4 = _destination_point(lat1, lon1, bearing + 90, half_w)
    ring = [[p[1], p[0]] for p in (p1, p2, p3, p4, p1)]
    return {"type": "Polygon", "coordinates": [ring]}


def _points_to_geojson(rows: list[dict[str, Any]]) -> dict[str, Any]:
    features = []
    for row in rows:
        lat, lon = row.get("latitude"), row.get("longitude")
        if lat is None or lon is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "properties": row,
        })
    return {"type": "FeatureCollection", "features": features}


def _adsb_rows(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Query the ADS-B live-feed sink read-only. A checkout without an active
    poller (the normal diagnostic state) simply advertises zero tracks.
    """
    if not ADSB_DB.is_file():
        return []
    uri = f"{ADSB_DB.resolve().as_uri()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(query, params).fetchall()]
    except sqlite3.Error as exc:
        log.warning("ADS-B track entity unavailable: %s", exc)
        return []


@app.get("/api/geo/observations.geojson")
def geo_observations() -> dict[str, Any]:
    return _points_to_geojson(load_observations())


@app.get("/api/geo/airports.geojson")
def geo_airports() -> dict[str, Any]:
    return _points_to_geojson(load_airports())


@app.get("/api/geo/infrastructure.geojson")
def geo_infrastructure() -> dict[str, Any]:
    if PuertoRicoInfrastructure is None:
        return {"type": "FeatureCollection", "features": []}
    infra = PuertoRicoInfrastructure()
    features = [
        {
            "type": "Feature",
            "geometry": _circle_polygon(f.latitude, f.longitude, f.radius_nm),
            "properties": {
                "feature_id": f.feature_id,
                "name": f.name,
                "type": f.type.value,
                "operator": f.operator,
                "sector": f.sector,
                "radius_nm": f.radius_nm,
                "operational_notes": f.operational_notes,
            },
        }
        for f in infra.features.values()
    ]
    return {"type": "FeatureCollection", "features": features}


@app.get("/api/geo/corridors.geojson")
def geo_corridors() -> dict[str, Any]:
    if CorridorAnalyzer is None or PuertoRicoInfrastructure is None:
        return {"type": "FeatureCollection", "features": []}
    analyzer = CorridorAnalyzer(PuertoRicoInfrastructure())
    features = [
        {
            "type": "Feature",
            "geometry": _corridor_polygon(c.start_point, c.end_point, c.width_nm),
            "properties": {
                "corridor_id": c.corridor_id,
                "name": c.name,
                "purpose": c.purpose,
                "typical_operator": c.typical_operator,
                "activity_level": c.activity_level,
                "width_nm": c.width_nm,
            },
        }
        for c in analyzer.corridors
    ]
    return {"type": "FeatureCollection", "features": features}


@app.get("/api/geo/observations/heatmap.geojson")
def geo_observations_heatmap() -> dict[str, Any]:
    if HeatmapGenerator is None:
        return {"type": "FeatureCollection", "features": []}
    generator = HeatmapGenerator()
    for row in load_observations():
        lat, lon = row.get("latitude"), row.get("longitude")
        if lat is not None and lon is not None:
            generator.add_point(float(lat), float(lon))
    return generator.get_geojson()


@app.get("/api/geo/tracks/{icao24}.geojson")
def geo_track(icao24: str) -> dict[str, Any]:
    """A single aircraft's ADS-B track as a GeoJSON LineString. The same
    point-list-to-LineString shape as the Spiderweb bridge export's
    _line_string() (spiderweb_export.py), kept as a local one-liner rather
    than an import across the src/skywatcher package boundary: unlike
    gis_intelligence.py, this endpoint has no reason to ever hard-fail when
    that boundary is unavailable (e.g. the frozen desktop build).
    """
    rows = _adsb_rows(
        """SELECT icao24, callsign, latitude, longitude, time_position
           FROM adsb_state_vectors
           WHERE icao24 = ? AND latitude IS NOT NULL AND longitude IS NOT NULL
           ORDER BY time_position ASC""",
        (icao24,),
    )
    coords = [[float(r["longitude"]), float(r["latitude"])] for r in rows]
    if len(coords) < 2:
        return {"type": "FeatureCollection", "features": []}
    geometry = {"type": "LineString", "coordinates": coords}
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "icao24": icao24,
                "callsign": rows[0].get("callsign"),
                "point_count": len(rows),
                "first_time_position": rows[0].get("time_position"),
                "last_time_position": rows[-1].get("time_position"),
            },
        }],
    }


@app.get("/api/geo/tracks")
def geo_track_index() -> list[dict[str, Any]]:
    """Distinct aircraft with a recorded ADS-B track, for a track-picker UI.
    Empty on a checkout without an active poller, same as geo_track above.
    """
    rows = _adsb_rows(
        """SELECT icao24, callsign, COUNT(*) AS point_count
           FROM adsb_state_vectors
           WHERE latitude IS NOT NULL AND longitude IS NOT NULL
           GROUP BY icao24
           HAVING COUNT(*) >= 2
           ORDER BY point_count DESC"""
    )
    return [
        {
            "icao24": r["icao24"],
            "callsign": r.get("callsign"),
            "point_count": r["point_count"],
        }
        for r in rows
    ]


def _load_municipios() -> dict[str, Any]:
    if not MUNICIPIOS_PATH.is_file():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(MUNICIPIOS_PATH.read_text(encoding="utf-8"))


@app.get("/api/geo/municipios.geojson")
def geo_municipios() -> dict[str, Any]:
    return _load_municipios()


@app.get("/api/geo/municipios/observation_density.geojson")
def geo_municipios_observation_density() -> dict[str, Any]:
    """Municipios polygons with an observation count baked into each
    feature's properties, keyed by matching `load_observations()`'s
    `municipality` field against each municipio's own `name` property (the
    same name->GEOID join aguayluz-pr's event_density and spiderweb-pr's
    gazetteer density use — no spatial join, no new geospatial dependency).
    """
    municipios = _load_municipios()
    by_name: Counter[str] = Counter()
    unmatched = 0
    names = {f["properties"].get("name") for f in municipios["features"]}
    for row in load_observations():
        name = row.get("municipality")
        if name in names:
            by_name[name] += 1
        else:
            unmatched += 1
    max_count = max(by_name.values(), default=0)
    for feature in municipios["features"]:
        name = feature["properties"].get("name")
        count = by_name.get(name, 0)
        feature["properties"]["observation_count"] = count
        feature["properties"]["observation_density_norm"] = (
            count / max_count if max_count else 0
        )
    municipios["unmatched_observations"] = unmatched
    return municipios
