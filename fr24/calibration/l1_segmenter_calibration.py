"""L1 SATIM calibration: FR24 UI segmenter geometry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .models import LayerCalibrationResult, write_json

try:  # pragma: no cover - exercised when repo module is importable
    from fr24.ui_segmenter import MAP_BOTTOM_FRAC, MAP_TOP_FRAC, PANEL_TOP_FRAC, UI_LEFT_FRAC, UI_RIGHT_FRAC
except Exception:  # fallback keeps calibration tests independent
    MAP_TOP_FRAC = 0.08
    MAP_BOTTOM_FRAC = 0.72
    PANEL_TOP_FRAC = 0.72
    UI_LEFT_FRAC = 0.04
    UI_RIGHT_FRAC = 0.96

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".heic"}


def compute_fractional_boxes(width: int, height: int) -> Dict[str, Tuple[int, int, int, int]]:
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    return {
        "map_bbox": (
            int(width * UI_LEFT_FRAC),
            int(height * MAP_TOP_FRAC),
            int(width * UI_RIGHT_FRAC),
            int(height * MAP_BOTTOM_FRAC),
        ),
        "panel_bbox": (
            int(width * UI_LEFT_FRAC),
            int(height * PANEL_TOP_FRAC),
            int(width * UI_RIGHT_FRAC),
            height,
        ),
    }


def list_images(path: str | Path) -> List[Path]:
    root = Path(path)
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*") if p.suffix.lower() in IMAGE_EXTENSIONS)


def score_annotations(rows: Iterable[Dict[str, Any]]) -> Dict[str, float]:
    total_route = 0.0
    route_in_map = 0.0
    panel_overlap = 0.0
    for row in rows:
        total_route += float(row.get("route_pixels_total", 0) or 0)
        route_in_map += float(row.get("route_pixels_in_map", 0) or 0)
        panel_overlap += float(row.get("panel_text_pixels_in_map", 0) or 0)
    return {
        "route_pixel_coverage": (route_in_map / total_route) if total_route else 0.0,
        "panel_text_overlap_pixels": panel_overlap,
    }


def load_annotation_json(path: str | None) -> List[Dict[str, Any]]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return list(data.get("annotations", []))


def calibrate(input_dir: str, annotations: str | None = None) -> Dict[str, Any]:
    images = list_images(input_dir)
    annotation_metrics = score_annotations(load_annotation_json(annotations))
    thresholds = {
        "route_pixel_coverage_min": 0.90,
        "panel_text_overlap_max": 0,
    }
    findings: List[Dict[str, Any]] = []
    if not images:
        findings.append({"severity": "warning", "detail": "no screenshot images found"})
    if annotation_metrics["route_pixel_coverage"] and annotation_metrics["route_pixel_coverage"] < thresholds["route_pixel_coverage_min"]:
        findings.append({"severity": "blocker", "detail": "map bbox captures less than 90% of annotated route pixels"})
    if annotation_metrics["panel_text_overlap_pixels"] > thresholds["panel_text_overlap_max"]:
        findings.append({"severity": "blocker", "detail": "map bbox overlaps annotated panel text"})
    status = "READY"
    if not images:
        status = "MISSING"
    elif any(f["severity"] == "blocker" for f in findings):
        status = "DEGRADED"
    return LayerCalibrationResult(
        layer="L1_ui_segmenter",
        status=status,
        metrics={"image_count": len(images), **annotation_metrics},
        thresholds=thresholds,
        findings=findings,
    ).to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate SATIM L1 FR24 UI segmentation geometry")
    parser.add_argument("--input", required=True, help="Directory of FR24 screenshots")
    parser.add_argument("--annotations", help="Optional JSON annotations for route/panel overlap scoring")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    write_json(args.output, calibrate(args.input, args.annotations))


if __name__ == "__main__":
    main()
