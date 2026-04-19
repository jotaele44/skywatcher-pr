"""
PR Intelligence System — FastAPI REST API
==========================================
Endpoints:
  GET  /health                   — liveness + file-existence check
  GET  /anomalies                — paginated anomaly list with bbox / score filters
  GET  /anomalies/{cell_id}      — single anomaly detail
  GET  /stats                    — summary statistics
  GET  /snapshots                — list timestamped snapshot files
  POST /pipeline/run             — trigger the 6-step pipeline in the background
  GET  /pipeline/status          — poll running / done / failed state

Usage:
  cd pr_intelligence_system
  uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import sys
import glob
from typing import Optional, List

# Ensure project root on sys.path so relative imports work
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api.models import (
    AnomalyFeature,
    AnomalyListResponse,
    StatsResponse,
    SnapshotInfo,
    SnapshotListResponse,
    PipelineRunResponse,
    PipelineStatusResponse,
    HealthResponse,
)
from api import pipeline as _pipeline

OUTPUT_DIR       = os.path.join(_PROJECT_ROOT, 'data', 'output')
ANOMALY_FILE     = os.path.join(OUTPUT_DIR, 'final_anomaly_ranked.csv')
ENRICHED_FILE    = os.path.join(OUTPUT_DIR, 'unified_features_enriched.csv')
SNAPSHOTS_DIR    = os.path.join(OUTPUT_DIR, 'snapshots')

app = FastAPI(
    title='PR Intelligence System API',
    description='Geospatial anomaly detection over Puerto Rico satellite data.',
    version='1.0.0',
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_anomalies() -> pd.DataFrame:
    if not os.path.exists(ANOMALY_FILE):
        raise HTTPException(status_code=503, detail='Anomaly file not yet generated. Run the pipeline first.')
    try:
        return pd.read_csv(ANOMALY_FILE)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'Failed to read anomaly file: {exc}')


def _row_to_feature(row: dict) -> AnomalyFeature:
    def _opt(key, cast=None):
        v = row.get(key)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return cast(v) if cast else v

    return AnomalyFeature(
        cell_id=str(row.get('cell_id', '')),
        lat=float(row['lat']),
        lon=float(row['lon']),
        grid_lat=_opt('grid_lat', float),
        grid_lon=_opt('grid_lon', float),
        raster_value=_opt('raster_value', float),
        source_format=_opt('source_format'),
        elevation_proxy=_opt('elevation_proxy', float),
        slope=_opt('slope', float),
        slope_class=_opt('slope_class'),
        physics_score=_opt('physics_score', float),
        spatial_anomaly_score=_opt('spatial_anomaly_score', float),
        composite_score=_opt('composite_score', float),
        final_score=_opt('final_score', float),
        anomaly_rank=_opt('anomaly_rank', int),
        classification=_opt('classification'),
        confidence=_opt('confidence', float),
        persistence=_opt('persistence', float),
        cluster=_opt('cluster', int),
        cluster_size=_opt('cluster_size', int),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get('/health', response_model=HealthResponse, tags=['System'])
def health():
    """Liveness check. Reports whether output files exist and pipeline state."""
    ps = _pipeline.get_status()
    return HealthResponse(
        status='ok',
        anomaly_file_exists=os.path.exists(ANOMALY_FILE),
        enriched_file_exists=os.path.exists(ENRICHED_FILE),
        pipeline_status=ps['status'],
    )


@app.get('/anomalies', response_model=AnomalyListResponse, tags=['Anomalies'])
def list_anomalies(
    min_lat:   Optional[float] = Query(None, description='Bounding-box south edge'),
    max_lat:   Optional[float] = Query(None, description='Bounding-box north edge'),
    min_lon:   Optional[float] = Query(None, description='Bounding-box west edge'),
    max_lon:   Optional[float] = Query(None, description='Bounding-box east edge'),
    min_score: Optional[float] = Query(None, description='Minimum final_score'),
    source:    Optional[str]   = Query(None, description='Filter by source_format'),
    cluster:   Optional[int]   = Query(None, description='Filter by cluster ID'),
    limit:     int             = Query(100, ge=1, le=5000, description='Max rows returned'),
    offset:    int             = Query(0, ge=0, description='Row offset for pagination'),
):
    """Return ranked anomalies with optional spatial / score / source filters."""
    df = _load_anomalies()

    if min_lat is not None:
        df = df[df['lat'] >= min_lat]
    if max_lat is not None:
        df = df[df['lat'] <= max_lat]
    if min_lon is not None:
        df = df[df['lon'] >= min_lon]
    if max_lon is not None:
        df = df[df['lon'] <= max_lon]
    if min_score is not None and 'final_score' in df.columns:
        df = df[df['final_score'] >= min_score]
    if source is not None and 'source_format' in df.columns:
        df = df[df['source_format'] == source]
    if cluster is not None and 'cluster' in df.columns:
        df = df[df['cluster'] == cluster]

    # Sort by final_score descending if present
    if 'final_score' in df.columns:
        df = df.sort_values('final_score', ascending=False)

    total = len(df)
    page  = df.iloc[offset: offset + limit]

    items = [_row_to_feature(row) for row in page.to_dict('records')]
    return AnomalyListResponse(total=total, returned=len(items), items=items)


@app.get('/anomalies/{cell_id}', response_model=AnomalyFeature, tags=['Anomalies'])
def get_anomaly(cell_id: str):
    """Return detail for a specific grid cell."""
    df = _load_anomalies()
    if 'cell_id' not in df.columns:
        raise HTTPException(status_code=500, detail='cell_id column missing from anomaly file')
    matches = df[df['cell_id'] == cell_id]
    if matches.empty:
        raise HTTPException(status_code=404, detail=f'cell_id {cell_id!r} not found')
    return _row_to_feature(matches.iloc[0].to_dict())


@app.get('/stats', response_model=StatsResponse, tags=['Analytics'])
def stats():
    """Summary statistics derived from the anomaly file."""
    df = _load_anomalies()
    total_features = len(df)

    sources: List[str] = []
    if 'source_format' in df.columns:
        sources = sorted(df['source_format'].dropna().unique().tolist())

    top_score  = None
    mean_score = None
    top_cell   = None
    if 'final_score' in df.columns:
        scores = df['final_score'].dropna()
        if len(scores):
            top_score  = float(scores.max())
            mean_score = float(scores.mean())

    if 'final_score' in df.columns and 'cell_id' in df.columns:
        idx = df['final_score'].idxmax() if not df['final_score'].isna().all() else None
        if idx is not None:
            top_cell = str(df.loc[idx, 'cell_id'])

    ps = _pipeline.get_status()
    return StatsResponse(
        total_features=total_features,
        total_anomalies=total_features,
        sources=sources,
        top_score=top_score,
        mean_score=mean_score,
        top_cell_id=top_cell,
        pipeline_last_run=ps.get('finished_at'),
    )


@app.get('/snapshots', response_model=SnapshotListResponse, tags=['Analytics'])
def list_snapshots():
    """List timestamped snapshot CSV files produced by the pipeline."""
    if not os.path.isdir(SNAPSHOTS_DIR):
        return SnapshotListResponse(total=0, snapshots=[])

    pattern = os.path.join(SNAPSHOTS_DIR, 'snapshot_*.csv')
    files   = sorted(glob.glob(pattern), reverse=True)

    items = []
    for fp in files:
        fname = os.path.basename(fp)
        # filename format: snapshot_YYYYMMDD_HHMMSS.csv
        parts = fname.replace('snapshot_', '').replace('.csv', '').split('_')
        ts = '_'.join(parts) if parts else fname

        rows = None
        try:
            rows = sum(1 for _ in open(fp)) - 1  # fast line count
        except Exception:
            pass

        items.append(SnapshotInfo(filename=fname, timestamp=ts, rows=rows))

    return SnapshotListResponse(total=len(items), snapshots=items)


@app.post('/pipeline/run', response_model=PipelineRunResponse, tags=['Pipeline'])
def run_pipeline():
    """Trigger the full 6-step pipeline in the background.

    Returns immediately.  Poll `/pipeline/status` to track progress.
    If a pipeline run is already in progress, returns status='already_running'.
    """
    result = _pipeline.trigger_pipeline()
    return PipelineRunResponse(
        status=result['status'],
        message='Pipeline started' if result['status'] == 'started' else 'Pipeline already running',
        job_id=result.get('job_id'),
    )


@app.get('/pipeline/status', response_model=PipelineStatusResponse, tags=['Pipeline'])
def pipeline_status():
    """Return the current pipeline execution state."""
    s = _pipeline.get_status()
    return PipelineStatusResponse(
        status=s['status'],
        job_id=s['job_id'],
        started_at=s['started_at'],
        finished_at=s['finished_at'],
        exit_code=s['exit_code'],
        log_tail=s.get('log_tail'),
    )
