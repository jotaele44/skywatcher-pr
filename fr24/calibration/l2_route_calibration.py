"""L2 SATIM calibration: FR24 route-color extraction."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from .models import LayerCalibrationResult, write_json

from skywatcher.core.route_visual_constants import COLOR_RANGES, MIN_ROUTE_PIXELS

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def pixel_in_range(pixel: Sequence[int], ranges: Mapping[str, Mapping[str, Tuple[int, int]]]) -> bool:
    r, g, b = int(pixel[0]), int(pixel[1]), int(pixel[2])
    for spec in ranges.values():
        if spec["r"][0] <= r <= spec["r"][1] and spec["g"][0] <= g <= spec["g"][1] and spec["b"][0] <= b <= spec["b"][1]:
            return True
    return False


def count_route_pixels(image_path: str | Path, ranges: Mapping[str, Mapping[str, Tuple[int, int]]] = COLOR_RANGES) -> int:
    try:
        from PIL import Image  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Pillow is required to inspect image pixels") from exc
    count = 0
    with Image.open(image_path) as img:
        for pixel in img.convert("RGB").getdata():
            if pixel_in_range(pixel, ranges):
                count += 1
    return count


def list_images(path: str | Path) -> List[Path]:
    root = Path(path)
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*") if p.suffix.lower() in IMAGE_EXTENSIONS)


def sweep_min_route_pixels(counts: Iterable[int], candidates: Iterable[int] = (4, 6, 8, 12, 20)) -> Dict[int, int]:
    values = list(counts)
    return {threshold: sum(1 for value in values if value >= threshold) for threshold in candidates}


def calibrate(input_dir: str, blank_input: str | None = None, min_route_pixels: int = MIN_ROUTE_PIXELS) -> Dict[str, object]:
    images = list_images(input_dir)
    blanks = list_images(blank_input) if blank_input else []
    route_counts = [count_route_pixels(p) for p in images]
    blank_counts = [count_route_pixels(p) for p in blanks]
    blank_false_positives = sum(1 for count in blank_counts if count >= min_route_pixels)
    fpr = (blank_false_positives / len(blank_counts)) if blank_counts else 0.0
    findings = []
    if not images:
        findings.append({"severity": "warning", "detail": "no route calibration images found"})
    if fpr >= 0.05:
        findings.append({"severity": "blocker", "detail": "blank tile false positive rate exceeds 5%"})
    status = "READY"
    if not images:
        status = "MISSING"
    elif any(f["severity"] == "blocker" for f in findings):
        status = "DEGRADED"
    return LayerCalibrationResult(
        layer="L2_route_extractor",
        status=status,
        metrics={
            "image_count": len(images),
            "blank_image_count": len(blanks),
            "route_positive_images": sum(1 for count in route_counts if count >= min_route_pixels),
            "blank_false_positive_rate": fpr,
            "min_route_pixels": min_route_pixels,
            "threshold_sweep": sweep_min_route_pixels(route_counts),
        },
        thresholds={"blank_false_positive_rate_max": 0.05, "min_route_pixels": min_route_pixels},
        findings=findings,
    ).to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate SATIM L2 FR24 route color extraction")
    parser.add_argument("--input", required=True)
    parser.add_argument("--blank-input")
    parser.add_argument("--min-route-pixels", type=int, default=MIN_ROUTE_PIXELS)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    write_json(args.output, calibrate(args.input, args.blank_input, args.min_route_pixels))


if __name__ == "__main__":
    main()
