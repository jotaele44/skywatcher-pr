"""
PRIIS Backend API
=================
FastAPI orchestration layer for the Puerto Rico Integrated Intelligence System.
Provides REST endpoints for all PRIIS entities (SQLite-backed), SSE streaming
for pipeline jobs and RAG queries, and GeoJSON endpoints for spatial layers.

Start: uvicorn server.backend.main:app --reload --port 8000
(run from the repo root so relative paths resolve correctly)
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

import aiosqlite
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

log = logging.getLogger("priis.backend")

# ─── Paths ─────────────────────────────────────────────────────────────────────

# main.py lives at server/backend/main.py → root is two levels up
ROOT = Path(__file__).parent.parent.parent
DB_PATH = Path(__file__).parent.parent / "priis.db"
OUTPUT_DIR = ROOT / "outputs"

# Make sibling ingestion package importable for the startup migration hook.
_INGEST_DIR = Path(__file__).parent.parent / "ingestion"
if str(_INGEST_DIR) not in sys.path:
    sys.path.append(str(_INGEST_DIR))

# ─── Startup migrations ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run idempotent SQLite migrations on boot, then yield to request loop.

    Migrations are synchronous (sqlite3) and one-shot — fine to block startup.
    If priis.db doesn't exist yet we skip silently; seed_demo.py will create it
    and apply the schema (which already includes the migrated columns).
    """
    if DB_PATH.exists():
        try:
            from migrations import run_all as run_migrations  # type: ignore
            conn = sqlite3.connect(DB_PATH)
            try:
                result = run_migrations(conn)
                log.info("startup migrations applied: %s", result)
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 — log and continue serving
            log.warning("startup migrations skipped: %s", exc)
    else:
        log.info("priis.db missing at %s; skipping startup migrations", DB_PATH)
    yield

# ─── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="PRIIS API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job registry: job_id → subprocess.Popen
_jobs: dict = {}

# ─── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json_fields(row: dict, fields: list[str]) -> dict:
    for f in fields:
        if row.get(f):
            try:
                row[f] = json.loads(row[f])
            except (json.JSONDecodeError, TypeError):
                row[f] = []
    return row


async def _rows(query: str, params: tuple = ()) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            return [dict(r) for r in await cur.fetchall()]

# ─── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Liveness + DB integrity (T10-83).

    Reports the DB path/existence and, when the DB is present, runs
    ``PRAGMA integrity_check`` and counts user tables. ``status`` is ``ok`` only
    when the DB exists and integrity passes; ``degraded`` otherwise. Always
    returns 200 so a load balancer can read the body rather than guessing.
    """
    result: dict[str, Any] = {
        "status": "ok",
        "db": str(DB_PATH),
        "db_exists": DB_PATH.exists(),
    }
    if not DB_PATH.exists():
        result["status"] = "degraded"
        result["reason"] = "db_missing"
        return result
    try:
        integrity = (await _rows("PRAGMA integrity_check"))
        ok = bool(integrity) and str(
            next(iter(integrity[0].values()))
        ).lower() == "ok"
        tables = await _rows(
            "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table'"
        )
        result["integrity_ok"] = ok
        result["table_count"] = tables[0]["n"] if tables else 0
        if not ok:
            result["status"] = "degraded"
            result["reason"] = "integrity_check_failed"
    except Exception as exc:  # pragma: no cover - defensive
        result["status"] = "degraded"
        result["reason"] = f"db_error: {exc}"
    return result

# ─── Entity endpoints ──────────────────────────────────────────────────────────

@app.get("/agencies")
async def list_agencies():
    return await _rows("SELECT id, code, name FROM agencies")


@app.get("/vendors")
async def list_vendors():
    return await _rows("SELECT id, name, risk, tier FROM vendors")


@app.get("/sites")
async def list_sites():
    rows = await _rows(
        "SELECT id, name, kind, lat, lng, sensitive, infrastructure_class, "
        "municipio_geoid, tract_geoid, zcta_geoid FROM sites"
    )
    for r in rows:
        r["sensitive"] = bool(r["sensitive"])
    return rows


@app.get("/contracts")
async def list_contracts():
    return await _rows(
        "SELECT id, agency, vendor, site, amount, signed, status, tier, note, "
        "procurement_method FROM contracts"
    )


@app.get("/events")
async def list_events():
    rows = await _rows(
        "SELECT id, kind, at, site_id, ref_id, label, tier, "
        "registration, callsign, aircraft_type, operator, origin_code, "
        "destination_code, altitude_ft, ground_speed_mph, flight_status, "
        "image_path FROM events"
    )
    for r in rows:
        r["siteId"] = r.pop("site_id", None)
        r["refId"] = r.pop("ref_id", None)
        r["aircraftType"] = r.pop("aircraft_type", None)
        r["originCode"] = r.pop("origin_code", None)
        r["destinationCode"] = r.pop("destination_code", None)
        r["altitudeFt"] = r.pop("altitude_ft", None)
        r["groundSpeedMph"] = r.pop("ground_speed_mph", None)
        r["flightStatus"] = r.pop("flight_status", None)
        r["imagePath"] = r.pop("image_path", None)
    return rows


@app.get("/events/{flight_id}/track")
async def event_track(flight_id: str):
    """Ordered per-point ADS-B track for a flight event (route playback).

    Returns the position reports ingested by scripts/parse_adsb_archive.py into
    the track_points table, oldest first. Empty list if the flight has no track.
    """
    rows = await _rows(
        "SELECT ts, at, lat, lng, altitude_ft, speed, direction "
        "FROM track_points WHERE flight_id = ? ORDER BY ts",
        (flight_id,),
    )
    for r in rows:
        r["altitudeFt"] = r.pop("altitude_ft", None)
    return rows


@app.get("/anomalies")
async def list_anomalies():
    rows = await _rows(
        "SELECT id, title, category, score, band, site_id, summary, "
        "factors, contracts, event_ids, confidence, contradictions FROM anomalies"
    )
    for r in rows:
        r["siteId"] = r.pop("site_id", None)
        r["events"] = json.loads(r.pop("event_ids") or "[]")
        _parse_json_fields(r, ["factors", "contracts", "contradictions"])
    return rows


@app.get("/sources")
async def list_sources():
    return await _rows("SELECT id, name, tier, kind, status FROM sources")


@app.get("/investigations")
async def list_investigations():
    return await _rows("SELECT id, title, active_vector, status FROM investigations")


@app.get("/alerts")
async def list_alerts():
    return await _rows(
        "SELECT id, at, kind, title, tier, investigation, registration FROM alerts"
    )

# ─── Pipeline ──────────────────────────────────────────────────────────────────

class PipelineRunRequest(BaseModel):
    phase: Optional[int] = None
    images: Optional[int] = None


@app.post("/pipeline/run")
async def pipeline_run(req: PipelineRunRequest = PipelineRunRequest()):
    job_id = str(uuid.uuid4())
    cmd = ["python", str(ROOT / "run_all.py")]
    if req.phase is not None:
        cmd += ["--phase", str(req.phase)]
    if req.images is not None:
        cmd += ["--images", str(req.images)]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(ROOT),
    )
    _jobs[job_id] = proc
    return {"job_id": job_id, "status": "running"}


@app.get("/pipeline/status/{job_id}")
async def pipeline_status(job_id: str):
    proc = _jobs.get(job_id)
    if proc is None:
        raise HTTPException(404, "job not found")
    rc = proc.poll()
    if rc is None:
        return {"job_id": job_id, "status": "running"}
    return {"job_id": job_id, "status": "done" if rc == 0 else "error", "returncode": rc}


async def _stream_stdout(proc: subprocess.Popen) -> AsyncGenerator[dict, None]:
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, proc.stdout.readline)
        if not line:
            break
        yield {"data": line.rstrip()}
    yield {"event": "done", "data": json.dumps({"returncode": proc.poll()})}


@app.get("/pipeline/events/{job_id}")
async def pipeline_events(job_id: str):
    proc = _jobs.get(job_id)
    if proc is None:
        raise HTTPException(404, "job not found")
    return EventSourceResponse(_stream_stdout(proc))


@app.delete("/pipeline/{job_id}")
async def pipeline_stop(job_id: str):
    proc = _jobs.get(job_id)
    if proc is None:
        raise HTTPException(404, "job not found")
    proc.terminate()
    _jobs.pop(job_id, None)
    return {"job_id": job_id, "status": "terminated"}

# ─── GeoJSON layers ────────────────────────────────────────────────────────────

_ALLOWED_LAYERS = {
    # Operational overlays
    "flights", "sites", "anomalies", "corridors", "heatmap",
    # PR administrative geographies (TIGER/Line, joined via ingest_tiger_pr.py)
    "municipios", "tracts", "places", "barrios",
}
_EMPTY_FC: dict = {"type": "FeatureCollection", "features": []}


def _find_geojson(layer: str) -> Optional[Path]:
    candidates = [
        OUTPUT_DIR / f"{layer}.geojson",
        ROOT / "data" / f"{layer}.geojson",
        ROOT / f"{layer}.geojson",
    ]
    return next((p for p in candidates if p.exists()), None)


async def _sites_from_db() -> dict:
    rows = await _rows(
        "SELECT id, name, kind, lat, lng, sensitive, infrastructure_class FROM sites"
    )
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lng"], r["lat"]]},
            "properties": {
                "id": r["id"],
                "name": r["name"],
                "kind": r["kind"],
                "sensitive": bool(r["sensitive"]),
                "infrastructure_class": r.get("infrastructure_class"),
            },
        }
        for r in rows
        if r.get("lat") is not None and r.get("lng") is not None
    ]
    return {"type": "FeatureCollection", "features": features}


async def _anomalies_from_db() -> dict:
    rows = await _rows(
        "SELECT a.id, a.title, a.score, a.band, a.category, "
        "s.lat, s.lng FROM anomalies a LEFT JOIN sites s ON a.site_id = s.id"
    )
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lng"], r["lat"]]},
            "properties": {"id": r["id"], "title": r["title"], "score": r["score"], "band": r["band"]},
        }
        for r in rows
        if r.get("lat") is not None and r.get("lng") is not None
    ]
    return {"type": "FeatureCollection", "features": features}


@app.get("/geo/{layer}.geojson")
async def geo_layer(layer: str):
    if layer not in _ALLOWED_LAYERS:
        raise HTTPException(400, f"unknown layer '{layer}'")
    path = _find_geojson(layer)
    if path is not None:
        return FileResponse(str(path), media_type="application/geo+json")
    if layer == "sites":
        return JSONResponse(await _sites_from_db(), media_type="application/geo+json")
    if layer == "anomalies":
        return JSONResponse(await _anomalies_from_db(), media_type="application/geo+json")
    return JSONResponse(_EMPTY_FC, media_type="application/geo+json")

# ─── RAG / Query ───────────────────────────────────────────────────────────────

class RagQueryRequest(BaseModel):
    query: str
    top_k: int = 5
    no_context: bool = False


async def _stream_rag(query: str, top_k: int, no_context: bool) -> AsyncGenerator[dict, None]:
    cmd = ["python", str(ROOT / "query_llm.py"), query, "--top-k", str(top_k)]
    if no_context:
        cmd.append("--no-context")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(ROOT),
    )
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, proc.stdout.readline)
        if not line:
            break
        yield {"data": line.rstrip()}
    rc = proc.wait()
    yield {"event": "done", "data": json.dumps({"returncode": rc})}


@app.post("/rag/query")
async def rag_query(req: RagQueryRequest):
    return EventSourceResponse(_stream_rag(req.query, req.top_k, req.no_context))


@app.post("/rag/index")
async def rag_index():
    job_id = str(uuid.uuid4())
    proc = subprocess.Popen(
        ["python", str(ROOT / "rag_pipeline.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(ROOT),
    )
    _jobs[job_id] = proc
    return {"job_id": job_id, "status": "indexing"}
