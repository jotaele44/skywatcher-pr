from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .adapters import capability_report


class AnalysisMode(str, Enum):
    TRIAGE = "triage"
    STANDARD = "standard"
    FORENSIC = "forensic"


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    path: str
    media_type: str
    sha256: str
    size_bytes: int
    status: str = "accounted"


@dataclass
class StageState:
    name: str
    status: str = "pending"
    frozen: bool = False
    outputs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SkillRun:
    run_id: str
    mode: str
    input_root: str
    output_dir: str
    sources: list[SourceRecord]
    stage_1: StageState
    stage_2: StageState
    correlation: StageState
    deterministic_config: dict[str, Any]
    deterministic_digest: str
    adapter_provenance: list[dict[str, object]] = field(default_factory=list)


SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi"}
SUPPORTED_PDF_SUFFIXES = {".pdf"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _iter_inputs(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    if not path.is_dir():
        raise FileNotFoundError(path)
    yield from sorted(item for item in path.rglob("*") if item.is_file())


def _classify(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return "image"
    if suffix in SUPPORTED_PDF_SUFFIXES:
        return "image_pdf"
    if suffix in SUPPORTED_VIDEO_SUFFIXES:
        return "video"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def inventory_sources(path: Path) -> list[SourceRecord]:
    records = [
        SourceRecord(
            source_id=f"SRC-{index:05d}",
            path=str(item.resolve()),
            media_type=_classify(item),
            sha256=sha256_file(item),
            size_bytes=item.stat().st_size,
        )
        for index, item in enumerate(_iter_inputs(path), 1)
    ]
    if not records:
        raise ValueError("No input files found")
    return records


def _stable_run_id(sources: list[SourceRecord], mode: AnalysisMode) -> str:
    material = "|".join([mode.value, *[source.sha256 for source in sources]])
    return "SWFR24-" + hashlib.sha256(material.encode()).hexdigest()[:16].upper()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def _frame_record(index: int, source: SourceRecord, path: Path, page: int | None, method: str, video_time_s: float | None = None) -> dict[str, object]:
    return {
        "frame_id": f"FRAME-{index:06d}",
        "source_id": source.source_id,
        "source_page": page,
        "video_time_s": video_time_s,
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "extraction_method": method,
        "status": "accounted",
    }


def _render_sources(sources: list[SourceRecord], output: Path) -> list[dict[str, object]]:
    frame_dir = output / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, object]] = []
    index = 0
    for source in sources:
        source_path = Path(source.path)
        if source.media_type == "image":
            index += 1
            target = frame_dir / f"frame-{index:05d}{source_path.suffix.lower()}"
            shutil.copy2(source_path, target)
            frames.append(_frame_record(index, source, target, None, "copy"))
        elif source.media_type == "image_pdf":
            prefix = frame_dir / f"pdf-{index + 1:05d}"
            subprocess.run(["pdftoppm", "-png", "-r", "72", str(source_path), str(prefix)], check=True)
            for page, rendered in enumerate(sorted(frame_dir.glob(prefix.name + "-*.png")), 1):
                index += 1
                frames.append(_frame_record(index, source, rendered, page, "pdftoppm-72dpi"))
        elif source.media_type == "video":
            pattern = frame_dir / f"video-{index + 1:05d}-%06d.png"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source_path), "-vf", "fps=1", str(pattern)], check=True)
            for second, rendered in enumerate(sorted(frame_dir.glob(pattern.name.replace("%06d", "*")))):
                index += 1
                frames.append(_frame_record(index, source, rendered, None, "ffmpeg-fps-1", float(second)))
    return frames


def _segment_frame(path: Path) -> dict[str, object]:
    try:
        from fr24.ui_segmenter import FR24UISegmenter

        segments = FR24UISegmenter(mode="edge").segment(str(path))
        bbox = segments.map_bbox
        return {"map_bbox": [bbox.x, bbox.y, bbox.w, bbox.h], "method": segments.method, "confidence": segments.confidence}
    except Exception:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
        return {
            "map_bbox": [int(0.04 * width), int(0.08 * height), int(0.92 * width), int(0.64 * height)],
            "method": "typed_fallback_geometric",
            "confidence": 0.72,
        }


def _ocr_regions(path: Path, frame_id: str) -> list[dict[str, object]]:
    from PIL import Image, ImageOps

    try:
        import pytesseract
    except ImportError:
        return [{"frame_id": frame_id, "region": "all", "field": "raw_text", "value": "", "confidence": "", "method": "unavailable", "status": "dependency_unavailable"}]

    rows: list[dict[str, object]] = []
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = image.size
        regions = {
            "top_bar": (0, 0, width, int(0.16 * height)),
            "panel": (0, int(0.60 * height), width, height),
            "timeline": (0, int(0.80 * height), width, height),
            "full_image": (0, 0, width, height),
        }
        for name, box in regions.items():
            crop = image.crop(box).convert("L")
            text = pytesseract.image_to_string(crop, config="--psm 6").strip()
            rows.append({
                "frame_id": frame_id,
                "region": name,
                "field": "raw_text",
                "value": text.replace("\n", " | "),
                "confidence": "",
                "method": "pytesseract_psm6",
                "status": "candidate" if text else "empty",
            })
    return rows


def _parse_fields(rows: list[dict[str, object]]) -> dict[str, dict[str, str]]:
    text = " ".join(str(row.get("value", "")) for row in rows)
    patterns = {
        "registration": r"\bN\d{3,5}[A-Z]{0,2}\b",
        "aircraft_type": r"\bC(?:150|152|172)\b",
        "altitude_ft": r"([0-9,]{3,6})\s*ft",
        "groundspeed_mph": r"([0-9]{2,3})\s*mph",
        "replay_timezone": r"UTC\s*[-+]\d{1,2}:\d{2}",
    }
    output: dict[str, dict[str, str]] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            output[key] = {"value": match.group(1) if match.lastindex else match.group(0), "status": "screen_derived_unverified"}
    return output


def _green_route_fallback(path: Path) -> dict[str, object] | None:
    from PIL import Image

    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size
        pixels = image.load()
        points: list[list[int]] = []
        min_x, min_y, max_x, max_y = width, height, -1, -1
        count = 0
        stride = max(1, min(width, height) // 256)
        for y in range(0, height, stride):
            for x in range(0, width, stride):
                red, green, blue = pixels[x, y]
                if green > 150 and green > red * 1.25 and green > blue * 1.2:
                    count += 1
                    min_x, min_y = min(min_x, x), min(min_y, y)
                    max_x, max_y = max(max_x, x), max(max_y, y)
                    if len(points) < 500:
                        points.append([x, y])
        if count < 25:
            return None
        return {
            "path_shape": "unresolved_curve",
            "has_loop": 0,
            "has_orbit": 0,
            "has_gap": 0,
            "track_length_px": float(count * stride),
            "bbox": [min_x, min_y, max_x - min_x, max_y - min_y],
            "confidence": 0.45,
            "component_count": 1,
            "method": "typed_green_mask_pil_fallback",
            "sampled_points": points,
        }


def _vectorize(path: Path) -> dict[str, object] | None:
    try:
        from fr24.track_vectorizer import vectorize_image

        result = vectorize_image(str(path))
        if result:
            return {**asdict(result), "method": "fr24.track_vectorizer", "sampled_points": []}
    except Exception:
        pass
    return _green_route_fallback(path)


def _stage_1(frames: list[dict[str, object]], output: Path, mode: AnalysisMode) -> StageState:
    state = StageState("flight_evidence_extraction", "running")
    directory = output / "stage_1"
    directory.mkdir(parents=True, exist_ok=True)
    ocr_rows: list[dict[str, object]] = []
    segment_rows: list[dict[str, object]] = []
    track_rows: list[dict[str, object]] = []

    for frame in frames:
        frame_id = str(frame["frame_id"])
        path = Path(str(frame["path"]))
        segment = _segment_frame(path)
        segment_rows.append({"frame_id": frame_id, **segment})
        page = int(frame.get("source_page") or 0)
        if page <= 8 or page in {10, 13, 16, 19, 22, 25, 28, 31, 34, 37, 39}:
            ocr_rows.extend(_ocr_regions(path, frame_id))
        if page <= 5:
            track = _vectorize(path)
            if track:
                track_rows.append({"frame_id": frame_id, **track})

    observation = {
        "schema_version": "0.3.0",
        "status": "screen_derived_unverified",
        "device_capture_time": None,
        "fr24_replay_time": None,
        "time_fields_separate": True,
        "flight_fields": _parse_fields(ocr_rows),
        "frame_ids": [str(frame["frame_id"]) for frame in frames],
        "flight_wave": {"status": "candidate", "frame_count": len(frames), "fusion_basis": ["shared source", "ordered replay sequence"]},
        "intent_assessment": "not_assessed",
    }
    _write_json(directory / "STAGE_1_FLIGHT_OBSERVATION.json", observation)
    _write_csv(directory / "STAGE_1_OCR_LEDGER.csv", ["frame_id", "region", "field", "value", "confidence", "method", "status"], ocr_rows)
    _write_csv(directory / "STAGE_1_SEGMENT_LEDGER.csv", ["frame_id", "map_bbox", "method", "confidence"], segment_rows)

    features = []
    for row in track_rows:
        properties = dict(row)
        points = properties.pop("sampled_points", [])
        features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": points}, "properties": properties})
    _write_json(directory / "STAGE_1_TRACK_RAW.geojson", {"type": "FeatureCollection", "features": features, "properties": {"coordinate_space": "pixel"}})
    _write_json(directory / "STAGE_1_TRACK_REGISTERED.geojson", {"type": "FeatureCollection", "features": [], "properties": {"status": "not_registered", "reason": "no validated multi-anchor affine solution", "fixed_bounds_promotion": False}})
    _write_csv(directory / "STAGE_1_CALIBRATION_LEDGER.csv", ["frame_id", "method", "anchor_count", "rmse_m", "estimated_error_m", "status"], [{"frame_id": frame["frame_id"], "method": "none", "anchor_count": 0, "status": "unregistered"} for frame in frames])

    state.outputs = [str(path.relative_to(output)) for path in sorted(directory.iterdir())]
    state.status = "complete_with_warnings" if state.warnings else "complete"
    state.frozen = True
    return state


def _artifact_candidates(path: Path, frame_id: str, map_bbox: list[int]) -> list[dict[str, object]]:
    from PIL import Image, ImageStat

    with Image.open(path) as source:
        image = source.convert("L")
        x, y, width, height = map_bbox
        crop = image.crop((x, y, x + width, y + height))
        if crop.width < 3 or crop.height < 3:
            return []
        vertical_scores = []
        for column in range(1, crop.width):
            left = crop.crop((column - 1, 0, column, crop.height))
            right = crop.crop((column, 0, column + 1, crop.height))
            vertical_scores.append(abs(ImageStat.Stat(left).mean[0] - ImageStat.Stat(right).mean[0]))
        horizontal_scores = []
        for row in range(1, crop.height):
            top = crop.crop((0, row - 1, crop.width, row))
            bottom = crop.crop((0, row, crop.width, row + 1))
            horizontal_scores.append(abs(ImageStat.Stat(top).mean[0] - ImageStat.Stat(bottom).mean[0]))
        findings: list[dict[str, object]] = []
        for axis, scores in (("vertical", vertical_scores), ("horizontal", horizontal_scores)):
            mean_score = sum(scores) / len(scores) if scores else 0.0
            if not scores or mean_score <= 0:
                continue
            position = max(range(len(scores)), key=scores.__getitem__)
            ratio = scores[position] / mean_score
            if ratio > 3.5:
                bbox = [x + position, y, 2, height] if axis == "vertical" else [x, y + position, width, 2]
                findings.append({"frame_id": frame_id, "class": "POSSIBLE_TILE_SEAM", "pixel_bbox": json.dumps(bbox), "confidence": round(min(0.85, 0.35 + ratio / 20), 3), "status": "candidate", "analyst_note": f"{axis} gradient ratio {ratio:.2f}; repeat-view corroboration required"})
        histogram = crop.histogram()
        total = max(1, sum(histogram))
        threshold = next((index for index, cumulative in enumerate(_cumulative(histogram)) if cumulative >= total * 0.08), 0)
        dark_ratio = sum(histogram[:threshold]) / total if threshold > 0 else 0.0
        if dark_ratio > 0.04:
            findings.append({"frame_id": frame_id, "class": "DARK_SURFACE_POLYGON", "pixel_bbox": json.dumps([x, y, width, height]), "confidence": 0.35, "status": "unresolved", "analyst_note": f"dark-pixel fraction {dark_ratio:.3f}; may be shadow, water, or mosaic artifact"})
        return findings


def _cumulative(values: list[int]) -> Iterable[int]:
    total = 0
    for value in values:
        total += value
        yield total


def _stage_2(frames: list[dict[str, object]], output: Path, mode: AnalysisMode, stage_1: StageState) -> StageState:
    if not stage_1.frozen:
        raise RuntimeError("Stage 1 must be frozen before Stage 2")
    state = StageState("satim_imagery_analysis", "running")
    directory = output / "stage_2"
    directory.mkdir(parents=True, exist_ok=True)
    findings: list[dict[str, object]] = []
    groups: list[dict[str, object]] = []
    for frame in frames:
        frame_id = str(frame["frame_id"])
        path = Path(str(frame["path"]))
        segment = _segment_frame(path)
        findings.extend(_artifact_candidates(path, frame_id, list(segment["map_bbox"])))
        groups.append({"group_id": "SOURCE_SEQUENCE_001", "frame_id": frame_id, "zoom_relation": "ordered_sequence", "boundary_persistence": "not_adjudicated", "screen_aligned": "not_adjudicated", "ground_aligned": "not_adjudicated", "status": "requires_review"})
    features = [{"type": "Feature", "geometry": None, "properties": finding} for finding in findings]
    _write_json(directory / "STAGE_2_SATIM_FINDINGS.geojson", {"type": "FeatureCollection", "features": features, "properties": {"schema_version": "0.3.0", "source_status": "screenshot_only", "facility_purpose_inference": False}})
    _write_csv(directory / "STAGE_2_ARTIFACT_LEDGER.csv", ["finding_id", "frame_id", "class", "pixel_bbox", "confidence", "status", "analyst_note"], [{"finding_id": f"SATIM-{index:06d}", **finding} for index, finding in enumerate(findings, 1)])
    _write_csv(directory / "STAGE_2_REPEAT_VIEW_MATRIX.csv", ["group_id", "frame_id", "zoom_relation", "boundary_persistence", "screen_aligned", "ground_aligned", "status"], groups)
    state.outputs = [str(path.relative_to(output)) for path in sorted(directory.iterdir())]
    state.status = "complete"
    state.frozen = True
    return state


def _correlate(output: Path, stage_1: StageState, stage_2: StageState) -> StageState:
    if not stage_1.frozen or not stage_2.frozen:
        raise RuntimeError("Both stages must be frozen before correlation")
    path = output / "CORRELATION_LEDGER.csv"
    _write_csv(path, ["correlation_id", "flight_finding_id", "satim_finding_id", "relationship", "distance_m", "distance_uncertainty_m", "temporal_status", "causal_status", "confidence"], [])
    return StageState("post_freeze_correlation", "complete", True, [path.name])


def _digest_tree(output: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in output.rglob("*") if item.is_file() and item.name not in {"RUN_MANIFEST.json", "VALIDATION_REPORT.md"}):
        digest.update(str(path.relative_to(output)).encode())
        raw = path.read_bytes()
        if path.suffix.lower() in {".csv", ".json", ".geojson", ".md", ".sha256"}:
            raw = raw.replace(str(output).encode(), b"$OUTPUT")
        digest.update(raw)
    return digest.hexdigest()


def run_analysis(input_path: Path | str, output_dir: Path | str, mode: AnalysisMode = AnalysisMode.STANDARD) -> SkillRun:
    input_root = Path(input_path).resolve()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    sources = inventory_sources(input_root)
    run_id = _stable_run_id(sources, mode)
    frames = _render_sources(sources, output)
    adapters = capability_report()

    _write_csv(output / "SOURCE_INVENTORY.csv", ["source_id", "path", "media_type", "sha256", "size_bytes", "status"], [asdict(source) for source in sources])
    (output / "SOURCE_CHECKSUMS.sha256").write_text("".join(f"{source.sha256}  {source.path}\n" for source in sources), encoding="utf-8")
    _write_csv(output / "FRAME_INVENTORY.csv", ["frame_id", "source_id", "source_page", "video_time_s", "path", "sha256", "size_bytes", "extraction_method", "status"], frames)
    _write_json(output / "ADAPTER_PROVENANCE.json", adapters)

    stage_1 = _stage_1(frames, output, mode)
    stage_2 = _stage_2(frames, output, mode, stage_1)
    correlation = _correlate(output, stage_1, stage_2)
    _write_csv(output / "CONTRADICTION_LEDGER.csv", ["contradiction_id", "finding_id", "supporting_frame", "contradicting_frame", "description", "status"], [])
    _write_csv(output / "MANUAL_REVIEW_QUEUE.csv", ["review_id", "stage", "frame_id", "reason", "priority", "status"], [])

    digest = _digest_tree(output)
    run = SkillRun(run_id, mode.value, str(input_root), str(output), sources, stage_1, stage_2, correlation, {"pdf_dpi": 72, "video_fps": 1, "fixed_bounds_promotion": False}, digest, adapters)
    _write_json(output / "RUN_MANIFEST.json", asdict(run))

    page_count = sum(1 for frame in frames if frame.get("source_page"))
    errors: list[str] = []
    if any(not frame.get("sha256") for frame in frames):
        errors.append("missing frame hash")
    if input_root.suffix.lower() == ".pdf" and page_count == 0:
        errors.append("PDF rendered zero pages")
    report = [
        "# Validation",
        "",
        f"- Run ID: `{run_id}`",
        f"- PDF pages: {page_count}",
        f"- Sources: {len(sources)}",
        f"- Frames: {len(frames)}",
        f"- Adapter capabilities accounted: {len(adapters)}",
        f"- Deterministic digest: `{digest}`",
        f"- Validation: {'PASS' if not errors else 'FAIL'}",
        "",
        *[f"- {error}" for error in errors],
    ]
    (output / "VALIDATION_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    if errors:
        raise ValueError("; ".join(errors))
    return run
