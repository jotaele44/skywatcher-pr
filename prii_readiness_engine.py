"""Backward-compat shim. Logic moved to skywatcher.core.readiness_engine.
See docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""
from __future__ import annotations

from skywatcher.core.readiness_engine import (
    READINESS_STATUS_DEGRADED,
    READINESS_STATUS_NOT_READY,
    READINESS_STATUS_READY,
    READINESS_STATUS_READY_FOR_OPS,
    REQUIRED_REPORT_KEYS,
    PRIIReadinessEngine,
)

__all__ = [
    "READINESS_STATUS_DEGRADED",
    "READINESS_STATUS_NOT_READY",
    "READINESS_STATUS_READY",
    "READINESS_STATUS_READY_FOR_OPS",
    "REQUIRED_REPORT_KEYS",
    "PRIIReadinessEngine",
]
