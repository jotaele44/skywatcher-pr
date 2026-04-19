"""Pydantic response models for the PR Intelligence System API."""

from typing import List, Optional
from pydantic import BaseModel


class AnomalyFeature(BaseModel):
    cell_id: str
    lat: float
    lon: float
    grid_lat: Optional[float] = None
    grid_lon: Optional[float] = None
    raster_value: Optional[float] = None
    source_format: Optional[str] = None
    elevation_proxy: Optional[float] = None
    slope: Optional[float] = None
    slope_class: Optional[str] = None
    physics_score: Optional[float] = None
    spatial_anomaly_score: Optional[float] = None
    composite_score: Optional[float] = None
    final_score: Optional[float] = None
    anomaly_rank: Optional[int] = None
    classification: Optional[str] = None
    confidence: Optional[float] = None
    persistence: Optional[float] = None
    cluster: Optional[int] = None
    cluster_size: Optional[int] = None


class AnomalyListResponse(BaseModel):
    total: int
    returned: int
    items: List[AnomalyFeature]


class StatsResponse(BaseModel):
    total_features: int
    total_anomalies: int
    sources: List[str]
    top_score: Optional[float] = None
    mean_score: Optional[float] = None
    top_cell_id: Optional[str] = None
    pipeline_last_run: Optional[str] = None


class SnapshotInfo(BaseModel):
    filename: str
    timestamp: str
    rows: Optional[int] = None


class SnapshotListResponse(BaseModel):
    total: int
    snapshots: List[SnapshotInfo]


class PipelineRunResponse(BaseModel):
    status: str
    message: str
    job_id: Optional[str] = None


class PipelineStatusResponse(BaseModel):
    status: str          # idle | running | done | failed
    job_id: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None
    log_tail: Optional[List[str]] = None


class HealthResponse(BaseModel):
    status: str
    anomaly_file_exists: bool
    enriched_file_exists: bool
    pipeline_status: str
