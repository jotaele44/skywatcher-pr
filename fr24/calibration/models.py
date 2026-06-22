"""Shared SATIM calibration report models."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

SATIM_SCHEMA_VERSION = "satim.calibration.v1"
LAYER_STATUSES = {"READY", "PARTIAL", "DEGRADED", "MISSING"}
REQUIRED_BASE_LAYERS = ["L1_ui_segmenter", "L2_route_extractor", "L3_vision_ocr"]
ADVISORY_LAYERS = ["L4_aircraft_intelligence", "L5_tile_seam_shadow"]


@dataclass
class LayerCalibrationResult:
    layer: str
    status: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    thresholds: Dict[str, Any] = field(default_factory=dict)
    findings: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in LAYER_STATUSES:
            raise ValueError(f"invalid SATIM layer status: {self.status}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SATIMCalibrationReport:
    layers: Dict[str, Dict[str, Any]]
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    repo: str = "skywatcher-pr"
    schema_version: str = SATIM_SCHEMA_VERSION
    blocking_gaps: List[Dict[str, Any]] = field(default_factory=list)
    recommended_next_actions: List[str] = field(default_factory=list)
    overall_status: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["overall_status"] = self.overall_status or derive_overall_status(self.layers)
        derived_blocking_gaps, derived_next_actions = derive_gap_accounting(self.layers)
        payload["blocking_gaps"] = self.blocking_gaps or derived_blocking_gaps
        payload["recommended_next_actions"] = self.recommended_next_actions or derived_next_actions
        return payload


def layer_status_to_readiness(status: Optional[str]) -> str:
    if status == "READY":
        return "PASS"
    if status == "PARTIAL":
        return "WARN"
    if status in {"DEGRADED", "MISSING"}:
        return "FAIL"
    return "WARN"


def derive_overall_status(layers: Mapping[str, Mapping[str, Any]]) -> str:
    """Return SATIM readiness from per-layer statuses.

    L5 is optional for base FR24 screenshot intelligence. It degrades only the
    satellite/aerial imagery artifact workflow unless all other layers pass and
    L5 itself is explicitly degraded.
    """
    statuses = {name: data.get("status") for name, data in layers.items()}
    if any(statuses.get(layer) in {"DEGRADED", "MISSING", None} for layer in REQUIRED_BASE_LAYERS):
        return "DEGRADED"
    if statuses.get("L4_aircraft_intelligence") in {"DEGRADED", "MISSING", None}:
        return "PARTIAL"
    if statuses.get("L5_tile_seam_shadow") in {"DEGRADED", "MISSING", None}:
        return "PARTIAL"
    if all(status == "READY" for status in statuses.values()):
        return "READY_FOR_BATCH_ANALYSIS"
    return "PARTIAL"


def derive_gap_accounting(layers: Mapping[str, Mapping[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Derive operator-facing gaps from SATIM layer readiness.

    L1-L3 are base SATIM readiness gates. Any non-ready L1-L3 layer is a
    blocking gap because it prevents reliable FR24 screenshot batch analysis.
    L4 and L5 are surfaced as recommended next actions because they gate
    enrichment quality and imagery-artifact workflows rather than base FR24
    screenshot parsing.
    """
    blocking_gaps: List[Dict[str, Any]] = []
    recommended_next_actions: List[str] = []

    for layer in REQUIRED_BASE_LAYERS:
        status = layers.get(layer, {}).get("status")
        if status != "READY":
            blocking_gaps.append({
                "layer": layer,
                "status": status or "MISSING",
                "severity": "blocker",
                "detail": f"{layer} is required for SATIM batch readiness and is not READY.",
            })

    for layer in ADVISORY_LAYERS:
        status = layers.get(layer, {}).get("status")
        if status != "READY":
            recommended_next_actions.append(
                f"Resolve {layer} status {status or 'MISSING'} before production promotion."
            )

    return blocking_gaps, recommended_next_actions


def read_json(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def normalize_layer_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    if "layer" in payload and "status" in payload:
        name = str(payload["layer"])
        data = dict(payload)
        data.pop("layer", None)
        return {name: data}
    if "layers" in payload and isinstance(payload["layers"], Mapping):
        return dict(payload["layers"])
    raise ValueError("layer report must contain either {layer,status} or {layers}")


def merge_layer_reports(paths: Iterable[str | Path], output_path: str | Path) -> Dict[str, Any]:
    layers: Dict[str, Dict[str, Any]] = {}
    for path in paths:
        payload = read_json(path)
        layers.update(normalize_layer_payload(payload))
    report = SATIMCalibrationReport(layers=layers).to_dict()
    write_json(output_path, report)
    return report
