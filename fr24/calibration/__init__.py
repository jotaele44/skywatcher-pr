"""SATIM layer calibration package.

This package provides calibration harnesses for FR24 screenshot extraction
(L1-L4) and satellite/aerial imagery artifact discrimination (L5).
"""

from .models import (
    LAYER_STATUSES,
    SATIM_SCHEMA_VERSION,
    LayerCalibrationResult,
    SATIMCalibrationReport,
    merge_layer_reports,
)

__all__ = [
    "LAYER_STATUSES",
    "SATIM_SCHEMA_VERSION",
    "LayerCalibrationResult",
    "SATIMCalibrationReport",
    "merge_layer_reports",
]
