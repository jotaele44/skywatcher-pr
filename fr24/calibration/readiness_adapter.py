"""Backward-compatible SATIM calibration adapter for PRII readiness surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping

from .models import derive_overall_status, layer_status_to_readiness, read_json


def satim_report_to_legacy_calibration(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Convert SATIM v1 layer report into the legacy PRII calibration contract.

    The existing readiness engine expects {status, baseline_mode,
    calibration_flags, candidate_count}. This adapter preserves that contract
    while keeping the richer SATIM layer payload available under satim_layers.
    """
    layers = report.get("layers", {}) if isinstance(report.get("layers"), Mapping) else {}
    overall = str(report.get("overall_status") or derive_overall_status(layers))
    status_map = {
        "READY_FOR_BATCH_ANALYSIS": "PASS",
        "PARTIAL": "WARN",
        "DEGRADED": "FAIL",
        "DEGRADED_FOR_IMAGERY_ARTIFACT_ANALYSIS": "FAIL",
    }
    flags = []
    for name, payload in layers.items():
        if not isinstance(payload, Mapping):
            continue
        layer_status = payload.get("status")
        if layer_status in {"PARTIAL", "DEGRADED", "MISSING"}:
            flags.append({
                "metric": name,
                "value": layer_status,
                "action": "review SATIM layer findings before production promotion",
            })
    candidate_count = 0
    for payload in layers.values():
        if isinstance(payload, Mapping):
            metrics = payload.get("metrics", {})
            if isinstance(metrics, Mapping):
                candidate_count += int(metrics.get("record_count") or metrics.get("candidate_count") or metrics.get("image_count") or 0)
    return {
        "status": status_map.get(overall, layer_status_to_readiness(overall)),
        "baseline_mode": "operational" if overall == "READY_FOR_BATCH_ANALYSIS" else "calibration",
        "calibration_flags": flags,
        "candidate_count": candidate_count,
        "schema_version": report.get("schema_version"),
        "satim_overall_status": overall,
        "satim_layers": layers,
    }


def load_satim_or_legacy(path: str | Path) -> Dict[str, Any]:
    payload = read_json(path)
    if payload.get("schema_version") == "satim.calibration.v1":
        return satim_report_to_legacy_calibration(payload)
    return payload
