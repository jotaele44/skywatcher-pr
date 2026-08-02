"""Offline adapter from legacy SATIM outputs to ADR 0006 provisional signals.

This module performs no acquisition, model execution, database access, or network I/O.
It only validates and deterministically reshapes an already-produced SATIM record.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

_REQUIRED_SATIM_FIELDS = {
    "satim_output_id",
    "signal_domain",
    "observation_type",
    "lat",
    "lon",
    "evidence_tier",
    "confidence",
    "geometry_status",
    "source_layer",
}
_ALLOWED_TIERS = {"T1", "T2", "T3", "T4"}
_ALLOWED_GEOMETRY = {"located", "approximate", "unlocated", "invalid"}
_ALLOWED_METHODS = {
    "PIXEL_DIFFERENCE",
    "CALIBRATED_CHANGE_DETECTION",
    "TILE_SEAM_CLASSIFICATION",
    "OTHER",
}


class SatimSignalAdapterError(ValueError):
    """Raised when an input cannot be represented by the provisional contract."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _default_method(observation_type: str) -> str:
    if observation_type == "tile_seam":
        return "TILE_SEAM_CLASSIFICATION"
    return "CALIBRATED_CHANGE_DETECTION"


def adapt_satim_output(
    satim_output: Mapping[str, Any],
    *,
    source_artifact_ids: Sequence[str],
    method_version: str,
    created_at: str,
    method: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    signal_id: str | None = None,
) -> dict[str, Any]:
    """Return a deterministic ADR 0006 provisional-signal record.

    ``created_at`` is supplied by the caller so replaying pinned inputs can be
    byte-reproducible. Source artifact IDs are deduplicated and sorted.
    """
    missing = sorted(_REQUIRED_SATIM_FIELDS - set(satim_output))
    if missing:
        raise SatimSignalAdapterError(f"missing SATIM fields: {missing}")
    if satim_output["signal_domain"] != "terrain_imagery":
        raise SatimSignalAdapterError("signal_domain must be terrain_imagery")
    if satim_output["evidence_tier"] not in _ALLOWED_TIERS:
        raise SatimSignalAdapterError("unsupported evidence_tier")
    if satim_output["geometry_status"] not in _ALLOWED_GEOMETRY:
        raise SatimSignalAdapterError("unsupported geometry_status")

    try:
        confidence = float(satim_output["confidence"])
        lat = float(satim_output["lat"])
        lon = float(satim_output["lon"])
    except (TypeError, ValueError) as exc:
        raise SatimSignalAdapterError("lat, lon, and confidence must be numeric") from exc
    if not 0.0 <= confidence <= 1.0:
        raise SatimSignalAdapterError("confidence must be between 0 and 1")
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise SatimSignalAdapterError("coordinates are outside valid ranges")

    artifacts = sorted({str(value).strip() for value in source_artifact_ids if str(value).strip()})
    if not artifacts:
        raise SatimSignalAdapterError("at least one source_artifact_id is required")
    selected_method = method or _default_method(str(satim_output["observation_type"]))
    if selected_method not in _ALLOWED_METHODS:
        raise SatimSignalAdapterError(f"unsupported method: {selected_method}")
    if not method_version.strip():
        raise SatimSignalAdapterError("method_version is required")
    if not created_at.strip():
        raise SatimSignalAdapterError("created_at is required")

    result = {
        "satim_output_id": str(satim_output["satim_output_id"]),
        "observation_type": str(satim_output["observation_type"]),
        "location": {"lat": lat, "lon": lon},
        "evidence_tier": str(satim_output["evidence_tier"]),
        "geometry_status": str(satim_output["geometry_status"]),
        "source_layer": str(satim_output["source_layer"]),
        "notes": satim_output.get("notes"),
    }
    seed = {
        "source_artifact_ids": artifacts,
        "method": selected_method,
        "method_version": method_version,
        "parameters": dict(parameters or {}),
        "result": result,
    }
    resolved_signal_id = signal_id or (
        "satim-signal-" + hashlib.sha256(_canonical_json(seed).encode("utf-8")).hexdigest()[:24]
    )
    return {
        "schema_version": "satim_provisional_signal.v1",
        "signal_id": resolved_signal_id,
        "source_artifact_ids": artifacts,
        "method": selected_method,
        "method_version": method_version,
        "parameters": dict(parameters or {}),
        "result": result,
        "confidence": confidence,
        "provisional": True,
        "review_status": "NEEDS_REVIEW",
        "created_at": created_at,
    }
