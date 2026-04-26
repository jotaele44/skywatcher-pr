"""
FastAPI application for GEO-PR-INT.

Provides REST endpoints to query ILAP candidates, corridors, and contracts.
Loads data from the cache on first request (lazy initialisation).

Endpoints:
  GET  /health
  GET  /candidates
  GET  /candidates/{rank}
  GET  /corridors
  GET  /corridors/{corridor_id}
  GET  /contracts
  GET  /status
  POST /run
"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
    from fastapi.responses import JSONResponse
    _FASTAPI_OK = True
except ImportError:
    logger.warning("FastAPI not installed — API module will not be usable (pip install fastapi uvicorn)")
    _FASTAPI_OK = False

import pandas as pd

_cache: dict[str, Any] = {
    "candidates": None,
    "corridors":  None,
    "contracts":  None,
    "loaded_at":  None,
    "pipeline_running": False,
    "last_run_at": None,
    "last_run_result": None,
}


def _load_cache() -> None:
    """Lazy-load DataFrames from CacheManager on first request."""
    from storage.cache.cache_manager import CacheManager
    cm = CacheManager()
    if _cache["candidates"] is None:
        df = cm.load_candidates()
        _cache["candidates"] = df if df is not None else pd.DataFrame()
    if _cache["corridors"] is None:
        df = cm.load_corridors()
        _cache["corridors"] = df if df is not None else pd.DataFrame()
    if _cache["contracts"] is None:
        df = cm.load_contracts()
        _cache["contracts"] = df if df is not None else pd.DataFrame()
    if _cache["loaded_at"] is None:
        _cache["loaded_at"] = datetime.utcnow().isoformat()


def _df_to_records(df: pd.DataFrame) -> list[dict]:
    """Convert DataFrame to JSON-serialisable list of dicts."""
    return [
        {k: (None if isinstance(v, float) and pd.isna(v) else v)
         for k, v in row.items()}
        for _, row in df.iterrows()
    ]


def create_app() -> "FastAPI | None":
    """Factory function — returns the FastAPI app or None if FastAPI is not installed."""
    if not _FASTAPI_OK:
        return None

    app = FastAPI(
        title="GEO-PR-INT API",
        description="Geospatial Puerto Rico Intelligence System — ILAP candidate and corridor API",
        version="1.0.0",
    )

    # ── /health ───────────────────────────────────────────────────────────────

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "1.0.0", "timestamp": datetime.utcnow().isoformat()}

    # ── /candidates ───────────────────────────────────────────────────────────

    @app.get("/candidates")
    def list_candidates(
        limit:     int   = Query(100,  ge=1, le=10_000),
        min_score: float = Query(0.0,  ge=0),
        tier:      str   = Query("",   description="CRITICAL|HIGH|MEDIUM|LOW"),
        corridor_id: int = Query(-1,   description="Filter by corridor_id"),
    ):
        _load_cache()
        df: pd.DataFrame = _cache["candidates"]
        if df.empty:
            return []

        if "unified_score" in df.columns and min_score > 0:
            df = df[df["unified_score"] >= min_score]
        if tier and "score_tier" in df.columns:
            df = df[df["score_tier"] == tier.upper()]
        if corridor_id >= 0 and "corridor_id" in df.columns:
            df = df[df["corridor_id"] == corridor_id]
        if "unified_rank" in df.columns:
            df = df.sort_values("unified_rank")

        return JSONResponse(_df_to_records(df.head(limit)))

    @app.get("/candidates/{rank}")
    def get_candidate(rank: int):
        _load_cache()
        df: pd.DataFrame = _cache["candidates"]
        if df.empty:
            raise HTTPException(status_code=404, detail="No candidates loaded")
        if "unified_rank" in df.columns:
            row = df[df["unified_rank"] == rank]
        elif len(df) >= rank:
            row = df.iloc[[rank - 1]]
        else:
            raise HTTPException(status_code=404, detail=f"Rank {rank} not found")
        if row.empty:
            raise HTTPException(status_code=404, detail=f"Rank {rank} not found")
        return JSONResponse(_df_to_records(row)[0])

    # ── /corridors ────────────────────────────────────────────────────────────

    @app.get("/corridors")
    def list_corridors(
        min_r2: float = Query(0.0,  ge=0, le=1),
        limit:  int   = Query(100,  ge=1, le=1_000),
    ):
        _load_cache()
        df: pd.DataFrame = _cache["corridors"]
        if df.empty:
            return []
        if min_r2 > 0 and "linearity_r2" in df.columns:
            df = df[df["linearity_r2"] >= min_r2]
        if "mean_score" in df.columns:
            df = df.sort_values("mean_score", ascending=False)
        return JSONResponse(_df_to_records(df.head(limit)))

    @app.get("/corridors/{corridor_id}")
    def get_corridor(corridor_id: int):
        _load_cache()
        df: pd.DataFrame = _cache["corridors"]
        if df.empty:
            raise HTTPException(status_code=404, detail="No corridors loaded")
        if "corridor_id" not in df.columns:
            raise HTTPException(status_code=404, detail="corridor_id column missing")
        row = df[df["corridor_id"] == corridor_id]
        if row.empty:
            raise HTTPException(status_code=404, detail=f"Corridor {corridor_id} not found")
        return JSONResponse(_df_to_records(row)[0])

    # ── /contracts ────────────────────────────────────────────────────────────

    @app.get("/contracts")
    def list_contracts(
        keyword:    str   = Query("", description="Filter by keyword in description"),
        min_amount: float = Query(0.0, ge=0),
        limit:      int   = Query(100, ge=1, le=5_000),
    ):
        _load_cache()
        df: pd.DataFrame = _cache["contracts"]
        if df.empty:
            return []
        if keyword and "description" in df.columns:
            mask = df["description"].str.contains(keyword, case=False, na=False)
            df = df[mask]
        if min_amount > 0 and "obligated_amount" in df.columns:
            df = df[pd.to_numeric(df["obligated_amount"], errors="coerce").fillna(0) >= min_amount]
        if "obligated_amount" in df.columns:
            df = df.sort_values("obligated_amount", ascending=False)
        return JSONResponse(_df_to_records(df.head(limit)))

    # ── /status ───────────────────────────────────────────────────────────────

    @app.get("/status")
    def status():
        from storage.cache.cache_manager import CacheManager
        last_run = CacheManager.get_last_run_timestamp()
        _load_cache()
        return {
            "last_run_at":   last_run,
            "loaded_at":     _cache["loaded_at"],
            "pipeline_running": _cache["pipeline_running"],
            "candidate_count": len(_cache["candidates"]) if _cache["candidates"] is not None else 0,
            "corridor_count":  len(_cache["corridors"])  if _cache["corridors"]  is not None else 0,
            "contract_count":  len(_cache["contracts"])  if _cache["contracts"]  is not None else 0,
        }

    # ── /run ─────────────────────────────────────────────────────────────────

    def _background_run(live: bool, force_api: bool):
        _cache["pipeline_running"] = True
        try:
            from pipeline.full_run import run_full_pipeline
            result = run_full_pipeline(live_satellite=live, force_api=force_api)
            _cache["last_run_result"] = result
            _cache["last_run_at"] = datetime.utcnow().isoformat()
            # Invalidate cached DataFrames so next /candidates call reloads
            _cache["candidates"] = None
            _cache["corridors"]  = None
            _cache["contracts"]  = None
            _cache["loaded_at"]  = None
        except Exception as exc:
            logger.error(f"Background pipeline run failed: {exc}")
            _cache["last_run_result"] = {"error": str(exc)}
        finally:
            _cache["pipeline_running"] = False

    @app.post("/run")
    def trigger_run(
        background_tasks: BackgroundTasks,
        live:      bool = Query(False, description="Use live satellite data"),
        force_api: bool = Query(False, description="Force USASpending API query"),
    ):
        if _cache["pipeline_running"]:
            return {"status": "already_running"}
        background_tasks.add_task(_background_run, live=live, force_api=force_api)
        return {"status": "started", "message": "Pipeline running in background. Poll /status for updates."}

    return app
