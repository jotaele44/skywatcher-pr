"""Shared SATIM calibration report models."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

SATIM_SCHEMA_VERSION = "satim.calibration.v1"
LAYER_STATUSES = {"READY", "PARTIAL", "DEGRADED", "MISSING"}


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
    required = ["L1_ui_segmenter", "L2_route_extractor", "L3_vision_ocr"]
    if any(statuses.get(layer) in {"DEGRADED", "MISSING", None} for layer in required):
        return "DEGRADED"
    if statuses.get("L4_aircraft_intelligence") in {"DEGRADED", "MISSING", None}:
        return "PARTIAL"
    if statuses.get("L5_tile_seam_shadow") in {"DEGRADED", "MISSING", None}:
        return "PARTIAL"
    if all(status == "READY" for status in statuses.values()):
        return "READY_FOR_BATCH_ANALYSIS"
    return "PARTIAL"


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
