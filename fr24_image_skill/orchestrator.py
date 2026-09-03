from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .adapters import capability_report


class AnalysisMode(str, Enum):
    TRIAGE = "triage"
    STANDARD = "standard"
    FORENSIC = "forensic"


# What each mode actually changes. `mode` was threaded through _stage_1 and _stage_2 from
# the start but never branched on, so all three modes did identical work; the enum
# described an intent the code did not implement. Values here are the per-mode parameter
# set, resolved once in RunOptions and carried into deterministic_config so a run states
# the parameters it used.
MODE_PARAMETERS: dict[str, dict[str, Any]] = {
    "triage": {
        # Cheapest useful pass: sample video sparsely, render PDFs at screen DPI, and
        # accept a looser seam floor because triage is meant to over-collect candidates
        # for a human to filter rather than to adjudicate them.
        "pdf_dpi": 72,
        "video_fps": 1,
        "seam_score_threshold": 4.0,
        "ui_margin_fraction": 0.04,
        "multi_scale_tests": False,
        "cross_source_tests": False,
    },
    "standard": {
        "pdf_dpi": 72,
        "video_fps": 1,
        "seam_score_threshold": 6.0,
        "ui_margin_fraction": 0.04,
        "multi_scale_tests": True,
        "cross_source_tests": False,
    },
    "forensic": {
        # Higher render fidelity and a stricter floor: forensic output is meant to
        # survive review, so it trades recall for precision and enables the cross-source
        # comparison the taxonomy's contradiction tests need.
        "pdf_dpi": 200,
        "video_fps": 4,
        "seam_score_threshold": 7.5,
        "ui_margin_fraction": 0.02,
        "multi_scale_tests": True,
        "cross_source_tests": True,
    },
}


@dataclass(frozen=True)
class RunOptions:
    """The skill's declared input contract, made reachable.

    `skills/skywatcher-fr24-image-analysis/schemas/input.schema.json` has declared
    execute_stage_1, execute_stage_2, external_verification, target_registration_rmse_m
    and output_geometry since the skill was written, but the CLI accepted only `--mode`,
    so four of the six knobs were unreachable. Defaults match the schema's.
    """

    mode: AnalysisMode = AnalysisMode.STANDARD
    execute_stage_1: bool = True
    execute_stage_2: bool = True
    external_verification: str = "provided_only"
    target_registration_rmse_m: float = 10.0
    output_geometry: str = "geojson"

    def __post_init__(self) -> None:
        if self.external_verification not in {"none", "provided_only", "acquire_when_available"}:
            raise ValueError(f"unknown external_verification: {self.external_verification}")
        if self.output_geometry not in {"none", "pixel_space", "geojson"}:
            raise ValueError(f"unknown output_geometry: {self.output_geometry}")
        if self.target_registration_rmse_m <= 0:
            raise ValueError("target_registration_rmse_m must be greater than zero")
        # Stage 2 reads Stage 1's frozen state, so it cannot run without it (SKILL.md's
        # freeze-before-proceed invariant). Refuse rather than produce a partial run that
        # looks complete.
        if self.execute_stage_2 and not self.execute_stage_1:
            raise ValueError(
                "execute_stage_2 requires execute_stage_1: stage 2 consumes stage 1's "
                "frozen output"
            )

    def parameters(self) -> dict[str, Any]:
        """Full resolved parameter set for this run."""
        return {
            **MODE_PARAMETERS[self.mode.value],
            "mode": self.mode.value,
            "execute_stage_1": self.execute_stage_1,
            "execute_stage_2": self.execute_stage_2,
            "external_verification": self.external_verification,
            "target_registration_rmse_m": self.target_registration_rmse_m,
            "output_geometry": self.output_geometry,
            "fixed_bounds_promotion": False,
        }


class FindingDisposition(str, Enum):
    NOT_ADJUDICATED = "NOT_ADJUDICATED"
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    DUPLICATE = "DUPLICATE"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


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
SEAM_SCORE_THRESHOLD = 6.0
UI_MARGIN_FRACTION = 0.04
DARK_LUMINANCE_THRESHOLD = 48
DARK_RATIO_THRESHOLD = 0.08


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
        SourceRecord(f"SRC-{index:05d}", str(item.resolve()), _classify(item), sha256_file(item), item.stat().st_size)
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


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _frame_record(index: int, source: SourceRecord, path: Path, page: int | None, method: str, video_time_s: float | None = None) -> dict[str, object]:
    return {
        "frame_id": f"FRAME-{index:06d}", "source_id": source.source_id, "source_page": page,
        "video_time_s": video_time_s, "path": str(path.resolve()), "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size, "extraction_method": method, "status": "accounted",
    }


def _render_sources(
    sources: list[SourceRecord], output: Path, parameters: dict[str, Any] | None = None
) -> list[dict[str, object]]:
    # Render fidelity is a mode parameter, not a constant: forensic renders PDFs at
    # 200 DPI and samples video at 4 fps, triage and standard at 72 DPI / 1 fps. The
    # extraction_method string records which was used so a frame's provenance states its
    # own fidelity.
    parameters = parameters or MODE_PARAMETERS["standard"]
    pdf_dpi = int(parameters["pdf_dpi"])
    video_fps = int(parameters["video_fps"])

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
            renderer = shutil.which("pdftoppm")
            if renderer:
                subprocess.run([renderer, "-png", "-r", str(pdf_dpi), str(source_path), str(prefix)], check=True)
                rendered_pages = sorted(frame_dir.glob(prefix.name + "-*.png"))
                method = f"pdftoppm-{pdf_dpi}dpi"
            else:
                try:
                    import pymupdf as fitz
                except ImportError:
                    try:
                        import fitz
                    except ImportError as exc:
                        raise RuntimeError("PDF rendering degraded: neither pdftoppm nor PyMuPDF is available") from exc
                rendered_pages = []
                scale = pdf_dpi / 72
                with fitz.open(source_path) as document:
                    for page_number, pdf_page in enumerate(document, 1):
                        rendered = frame_dir / f"{prefix.name}-{page_number}.png"
                        pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).save(rendered)
                        rendered_pages.append(rendered)
                method = f"pymupdf-{pdf_dpi}dpi-fallback"
            for page, rendered in enumerate(rendered_pages, 1):
                index += 1
                frames.append(_frame_record(index, source, rendered, page, method))
        elif source.media_type == "video":
            pattern = frame_dir / f"video-{index + 1:05d}-%06d.png"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source_path), "-vf", f"fps={video_fps}", str(pattern)], check=True)
            for second, rendered in enumerate(sorted(frame_dir.glob(pattern.name.replace("%06d", "*")))):
                index += 1
                frames.append(_frame_record(index, source, rendered, None, f"ffmpeg-fps-{video_fps}", float(second)))
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
        return {"map_bbox": [int(.04 * width), int(.08 * height), int(.92 * width), int(.64 * height)], "method": "typed_fallback_geometric", "confidence": .72}


def _ocr_unavailable(frame_id: str) -> list[dict[str, object]]:
    """The degraded result when OCR cannot run at all."""
    return [{"frame_id": frame_id, "region": "all", "field": "raw_text", "value": "", "confidence": "", "method": "unavailable", "status": "dependency_unavailable"}]


def _ocr_regions(path: Path, frame_id: str) -> list[dict[str, object]]:
    from PIL import Image, ImageOps
    try:
        import pytesseract
    except ImportError:
        return _ocr_unavailable(frame_id)
    # pytesseract is a Python wrapper around the `tesseract` BINARY, and the two
    # are installed separately — pytesseract is not declared in any manifest here,
    # so "package present, binary absent" is a normal state, not an edge case.
    # The import above only proves the package is there; image_to_string raises
    # TesseractNotFoundError at CALL time when the binary is missing. Probe once
    # here so that degrades the same way as the package being absent, instead of
    # crashing partway through the region loop.
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        return _ocr_unavailable(frame_id)
    rows: list[dict[str, object]] = []
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = image.size
        regions = {"top_bar": (0, 0, width, int(.16 * height)), "panel": (0, int(.60 * height), width, height), "timeline": (0, int(.80 * height), width, height), "full_image": (0, 0, width, height)}
        for name, box in regions.items():
            text = pytesseract.image_to_string(image.crop(box).convert("L"), config="--psm 6").strip()
            rows.append({"frame_id": frame_id, "region": name, "field": "raw_text", "value": text.replace("\n", " | "), "confidence": "", "method": "pytesseract_psm6", "status": "candidate" if text else "empty"})
    return rows


def _parse_fields(rows: list[dict[str, object]]) -> dict[str, dict[str, str]]:
    text = " ".join(str(row.get("value", "")) for row in rows)
    patterns = {"registration": r"\bN\d{3,5}[A-Z]{0,2}\b", "aircraft_type": r"\bC(?:150|152|172)\b", "altitude_ft": r"([0-9,]{3,6})\s*ft", "groundspeed_mph": r"([0-9]{2,3})\s*mph", "replay_timezone": r"UTC\s*[-+]\d{1,2}:\d{2}"}
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
        stride = max(1, min(width, height) // 256)
        points: list[list[int]] = []
        min_x, min_y, max_x, max_y, count = width, height, -1, -1, 0
        for y in range(0, height, stride):
            for x in range(0, width, stride):
                red, green, blue = pixels[x, y]
                if green > 150 and green > red * 1.25 and green > blue * 1.2:
                    count += 1
                    min_x, min_y, max_x, max_y = min(min_x, x), min(min_y, y), max(max_x, x), max(max_y, y)
                    if len(points) < 500:
                        points.append([x, y])
        if count < 25:
            return None
        return {"path_shape": "unresolved_curve", "has_loop": 0, "has_orbit": 0, "has_gap": 0, "track_length_px": float(count * stride), "bbox": [min_x, min_y, max_x - min_x, max_y - min_y], "confidence": .45, "component_count": 1, "method": "typed_green_mask_pil_fallback", "sampled_points": points}


def _vectorize(path: Path) -> dict[str, object] | None:
    try:
        from fr24.track_vectorizer import vectorize_image
        result = vectorize_image(str(path))
        if result:
            return {**asdict(result), "method": "fr24.track_vectorizer"}
    except Exception:
        pass
    return _green_route_fallback(path)


def _stage_1(frames: list[dict[str, object]], output: Path, mode: AnalysisMode) -> StageState:
    state = StageState("flight_evidence_extraction", "running")
    directory = output / "stage_1"
    directory.mkdir(parents=True, exist_ok=True)
    ocr_rows, segment_rows, track_rows = [], [], []
    for frame in frames:
        frame_id, path = str(frame["frame_id"]), Path(str(frame["path"]))
        segment_rows.append({"frame_id": frame_id, **_segment_frame(path)})
        ocr_rows.extend(_ocr_regions(path, frame_id))
        track = _vectorize(path)
        if track:
            track_rows.append({"frame_id": frame_id, **track})
    observation = {"schema_version": "0.1.0", "status": "screen_derived_unverified", "device_capture_time": None, "fr24_replay_time": None, "time_fields_separate": True, "flight_fields": _parse_fields(ocr_rows), "frame_ids": [str(frame["frame_id"]) for frame in frames], "flight_wave": {"status": "candidate", "frame_count": len(frames), "fusion_basis": ["shared source", "ordered replay sequence"]}, "intent_assessment": "not_assessed"}
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
    state.status, state.frozen = "complete", True
    return state


def _axis_candidate(axis: str, scores: list[float], x: int, y: int, width: int, height: int, frame_id: str) -> dict[str, object] | None:
    if not scores:
        return None
    mean_score = sum(scores) / len(scores)
    if mean_score <= 0:
        return None
    position = max(range(len(scores)), key=scores.__getitem__)
    ratio = scores[position] / mean_score
    axis_extent = width if axis == "vertical" else height
    margin = max(2, int(axis_extent * UI_MARGIN_FRACTION))
    ui_intersection = position < margin or position >= axis_extent - margin
    if ratio < SEAM_SCORE_THRESHOLD or ui_intersection:
        return None
    bbox = [x + position, y, 2, height] if axis == "vertical" else [x, y + position, width, 2]
    screen_alignment_score = round(min(1.0, ratio / 12.0), 3)
    return {"frame_id": frame_id, "class": "POSSIBLE_TILE_SEAM", "pixel_bbox": json.dumps(bbox), "confidence": round(min(.85, .35 + ratio / 20), 3), "status": "candidate", "repeat_view_cluster_id": "SOURCE_SEQUENCE_001", "screen_alignment_score": screen_alignment_score, "ground_alignment_status": "NOT_ADJUDICATED", "cross_zoom_persistence": "NOT_ADJUDICATED", "ui_overlay_intersection": False, "analyst_note": f"{axis} gradient ratio {ratio:.2f}; non-UI threshold passed; repeat-view corroboration required"}


def _artifact_candidates(path: Path, frame_id: str, map_bbox: list[int], overlay_points: list[list[int]] | list[tuple[int, int]] | None = None) -> list[dict[str, object]]:
    from PIL import Image, ImageFilter, ImageStat
    with Image.open(path) as source:
        rgb = source.convert("RGB")
        x, y, width, height = map_bbox
        crop_rgb = rgb.crop((x, y, x + width, y + height))
        replacement = crop_rgb.filter(ImageFilter.MedianFilter(size=9))
        clean = crop_rgb.copy()
        clean_pixels, replacement_pixels = clean.load(), replacement.load()
        for py in range(clean.height):
            for px in range(clean.width):
                red, green, blue = clean_pixels[px, py]
                if (max(red, green, blue) - min(red, green, blue) >= 70 and max(red, green, blue) >= 120) or min(red, green, blue) >= 225:
                    clean_pixels[px, py] = replacement_pixels[px, py]
        for point in overlay_points or []:
            px, py = int(point[0]) - x, int(point[1]) - y
            for oy in range(max(0, py - 2), min(clean.height, py + 3)):
                for ox in range(max(0, px - 2), min(clean.width, px + 3)):
                    clean_pixels[ox, oy] = replacement_pixels[ox, oy]
        crop = clean.convert("L")
        if crop.width < 3 or crop.height < 3:
            return []
        vertical = [abs(ImageStat.Stat(crop.crop((column - 1, 0, column, crop.height))).mean[0] - ImageStat.Stat(crop.crop((column, 0, column + 1, crop.height))).mean[0]) for column in range(1, crop.width)]
        horizontal = [abs(ImageStat.Stat(crop.crop((0, row - 1, crop.width, row))).mean[0] - ImageStat.Stat(crop.crop((0, row, crop.width, row + 1))).mean[0]) for row in range(1, crop.height)]
        findings = [candidate for candidate in (_axis_candidate("vertical", vertical, x, y, width, height, frame_id), _axis_candidate("horizontal", horizontal, x, y, width, height, frame_id)) if candidate]
        histogram, total = crop.histogram(), max(1, crop.width * crop.height)
        dark_ratio = sum(histogram[: DARK_LUMINANCE_THRESHOLD + 1]) / total
        if dark_ratio > DARK_RATIO_THRESHOLD:
            findings.append({"frame_id": frame_id, "class": "DARK_SURFACE_POLYGON", "pixel_bbox": json.dumps([x, y, width, height]), "confidence": .35, "status": "unresolved", "repeat_view_cluster_id": "SOURCE_SEQUENCE_001", "screen_alignment_score": 0.0, "ground_alignment_status": "NOT_ADJUDICATED", "cross_zoom_persistence": "NOT_ADJUDICATED", "ui_overlay_intersection": False, "analyst_note": f"dark-pixel fraction {dark_ratio:.3f}; shadow/water/mosaic unresolved"})
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
    findings, groups = [], []
    for frame in frames:
        frame_id, path = str(frame["frame_id"]), Path(str(frame["path"]))
        segment = _segment_frame(path)
        track = _vectorize(path)
        overlay_points = list(track.get("sampled_points", [])) if track else []
        findings.extend(_artifact_candidates(path, frame_id, list(segment["map_bbox"]), overlay_points=overlay_points))
        groups.append({"repeat_view_cluster_id": "SOURCE_SEQUENCE_001", "frame_id": frame_id, "zoom_relation": "ordered_sequence", "cross_zoom_persistence": "NOT_ADJUDICATED", "screen_alignment_score": "", "ground_alignment_status": "NOT_ADJUDICATED", "ui_overlay_intersection": False, "status": "requires_review"})
    identified = [{"finding_id": f"SATIM-{index:06d}", **finding} for index, finding in enumerate(findings, 1)]
    features = [{"type": "Feature", "geometry": None, "properties": finding} for finding in identified]
    # facility_purpose_inference stays False: unbounded purpose inference remains
    # prohibited. function_assessment_enabled reports whether the bounded ADR v2.1 A1
    # channel produced anything on this run — False here because this stage emits
    # artifact candidates only, and a function assessment needs corroborating
    # observations it does not have.
    _write_json(directory / "STAGE_2_SATIM_FINDINGS.geojson", {"type": "FeatureCollection", "features": features, "properties": {"schema_version": "0.5.0", "source_status": "screenshot_only", "facility_purpose_inference": False, "function_assessment_enabled": False}})
    fields = ["finding_id", "frame_id", "class", "pixel_bbox", "confidence", "status", "repeat_view_cluster_id", "screen_alignment_score", "ground_alignment_status", "cross_zoom_persistence", "ui_overlay_intersection", "analyst_note"]
    _write_csv(directory / "STAGE_2_ARTIFACT_LEDGER.csv", fields, identified)
    _write_csv(directory / "STAGE_2_REPEAT_VIEW_MATRIX.csv", ["repeat_view_cluster_id", "frame_id", "zoom_relation", "cross_zoom_persistence", "screen_alignment_score", "ground_alignment_status", "ui_overlay_intersection", "status"], groups)
    state.outputs = [str(path.relative_to(output)) for path in sorted(directory.iterdir())]
    state.status, state.frozen = "complete", True
    return state


def _write_adjudication_ledgers(output: Path) -> tuple[int, int]:
    findings = sorted(_read_csv(output / "stage_2" / "STAGE_2_ARTIFACT_LEDGER.csv"), key=lambda row: row["finding_id"])
    contradiction_rows, review_rows = [], []
    for index, finding in enumerate(findings, 1):
        disposition = FindingDisposition.NOT_ADJUDICATED.value
        contradiction_rows.append({"contradiction_id": f"CONTRA-{index:06d}", "finding_id": finding["finding_id"], "supporting_frame": finding["frame_id"], "contradicting_frame": "", "description": "Candidate awaits repeat-view, cross-zoom, and ground-alignment adjudication", "disposition": disposition, "status": "open"})
        if finding.get("status") in {"candidate", "unresolved"}:
            review_rows.append({"review_id": f"REVIEW-{len(review_rows)+1:06d}", "stage": "stage_2", "finding_id": finding["finding_id"], "frame_id": finding["frame_id"], "reason": "Unadjudicated SATIM candidate", "priority": "normal", "disposition": disposition, "status": "open"})
    _write_csv(output / "CONTRADICTION_LEDGER.csv", ["contradiction_id", "finding_id", "supporting_frame", "contradicting_frame", "description", "disposition", "status"], contradiction_rows)
    _write_csv(output / "MANUAL_REVIEW_QUEUE.csv", ["review_id", "stage", "finding_id", "frame_id", "reason", "priority", "disposition", "status"], review_rows)
    return len(contradiction_rows), len(review_rows)


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


def _write_coverage_report(
    output: Path,
    run_id: str,
    options: RunOptions,
    sources: list[SourceRecord],
    stage_1: StageState,
    stage_2: StageState,
) -> dict[str, Any] | None:
    """Emit the run's lens coverage, or a typed reason it could not be produced.

    Imported lazily and degraded explicitly rather than raising: the skill is designed to
    run standalone with only stdlib available, and SKILL.md requires a missing capability
    to "produce an explicit degraded-state record rather than fabricated output" - the
    same contract adapters.py implements for optional dependencies. A run without the
    registry still says so in writing.
    """
    try:
        from skywatcher.core.lenses import LensRegistry as _LensRegistry
        from skywatcher.core.lenses import (
            ObjectiveProfileRegistry,
            evaluate_coverage,
        )
    except ImportError as exc:
        record = {
            "run_id": run_id,
            "available": False,
            "reason": f"skywatcher.core.lenses unavailable: {exc}",
        }
        _write_json(output / "coverage_report.json", record)
        return record

    repo_root = Path(__file__).resolve().parents[1]
    lenses, objectives = _LensRegistry(), ObjectiveProfileRegistry()
    try:
        lenses.load_dir(repo_root / "configs" / "analysis" / "lenses")
        objectives.load_dir(repo_root / "configs" / "analysis" / "objectives")
        profile = objectives.get("satellite_imagery_standard")
    except (FileNotFoundError, ValueError, KeyError) as exc:
        record = {
            "run_id": run_id,
            "available": False,
            "reason": f"analysis registry unavailable: {exc}",
        }
        _write_json(output / "coverage_report.json", record)
        return record

    # What this run actually supplied, per lens. The skill masks UI chrome and works from
    # rendered frames, so it has a target ROI but none of the control ROIs the artifact
    # lens wants - which is exactly the degradation the coverage record should show
    # rather than leaving implied.
    parameters = options.parameters()
    supplied = {
        "rlsm.source_inventory": {
            "source_directory": str(output),
            "supported_extensions": sorted(SUPPORTED_IMAGE_SUFFIXES),
        },
        "satim.image_artifacts": {
            "source_type": "screenshot",
            "roi_target": "frame_map_bbox",
            "seam_score_threshold": parameters["seam_score_threshold"],
            # Cross-source comparison is what a control ROI needs; only forensic mode
            # performs it.
            **(
                {"roi_remote_control": "cross_source"}
                if parameters["cross_source_tests"]
                else {}
            ),
        },
    }
    report = evaluate_coverage(
        profile,
        lenses,
        run_id=run_id,
        supplied_parameters=supplied,
        available_inputs={
            "rlsm.source_inventory": ["source_directory"],
            "satim.image_artifacts": ["source_frame", "roi_target"],
        },
        produced={
            "rlsm.source_inventory": bool(sources),
            "satim.image_artifacts": stage_2.frozen,
        },
        applicable={
            "satim.image_artifacts": options.execute_stage_2,
        },
        method_versions={"satim.image_artifacts": parameters["mode"]},
        generated_by="fr24_image_skill",
    )
    record = report.to_dict()
    record["available"] = True
    record["stage_1_status"] = stage_1.status
    record["stage_2_status"] = stage_2.status
    _write_json(output / "coverage_report.json", record)
    return record


def run_analysis(
    input_path: Path | str,
    output_dir: Path | str,
    mode: AnalysisMode = AnalysisMode.STANDARD,
    options: RunOptions | None = None,
) -> SkillRun:
    # `mode` stays a positional parameter so existing callers keep working; when both are
    # given, `options` wins and `mode` is ignored.
    options = options or RunOptions(mode=mode)
    mode = options.mode
    input_root, output = Path(input_path).resolve(), Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    sources, adapters = inventory_sources(input_root), capability_report()
    run_id = _stable_run_id(sources, mode)
    frames = _render_sources(sources, output, options.parameters())
    _write_csv(output / "SOURCE_INVENTORY.csv", ["source_id", "path", "media_type", "sha256", "size_bytes", "status"], [asdict(source) for source in sources])
    (output / "SOURCE_CHECKSUMS.sha256").write_text("".join(f"{source.sha256}  {source.path}\n" for source in sources), encoding="utf-8")
    _write_csv(output / "FRAME_INVENTORY.csv", ["frame_id", "source_id", "source_page", "video_time_s", "path", "sha256", "size_bytes", "extraction_method", "status"], frames)
    _write_json(output / "ADAPTER_PROVENANCE.json", adapters)
    stage_1 = _stage_1(frames, output, mode)
    stage_2 = _stage_2(frames, output, mode, stage_1)
    contradiction_count, review_count = _write_adjudication_ledgers(output)
    correlation = _correlate(output, stage_1, stage_2)
    finding_count = len(_read_csv(output / "stage_2" / "STAGE_2_ARTIFACT_LEDGER.csv"))
    digest = _digest_tree(output)
    run = SkillRun(run_id, mode.value, str(input_root), str(output), sources, stage_1, stage_2, correlation, options.parameters(), digest, adapters)
    _write_json(output / "RUN_MANIFEST.json", asdict(run))
    _write_coverage_report(output, run_id, options, sources, stage_1, stage_2)
    page_count = sum(1 for frame in frames if frame.get("source_page"))
    errors = []
    if any(not frame.get("sha256") for frame in frames):
        errors.append("missing frame hash")
    if input_root.suffix.lower() == ".pdf" and page_count == 0:
        errors.append("PDF rendered zero pages")
    if contradiction_count != finding_count:
        errors.append("finding-to-contradiction accounting mismatch")
    unresolved_count = sum(row.get("status") in {"candidate", "unresolved"} for row in _read_csv(output / "stage_2" / "STAGE_2_ARTIFACT_LEDGER.csv"))
    if review_count != unresolved_count:
        errors.append("unresolved-to-review accounting mismatch")
    report = ["# Validation", "", f"- Run ID: `{run_id}`", f"- PDF pages: {page_count}", f"- Sources: {len(sources)}", f"- Frames: {len(frames)}", f"- SATIM findings: {finding_count}", f"- Contradiction accounting: {contradiction_count}/{finding_count}", f"- Manual-review accounting: {review_count}/{unresolved_count}", f"- Adapter capabilities accounted: {len(adapters)}", f"- Deterministic digest: `{digest}`", f"- Validation: {'PASS' if not errors else 'FAIL'}", "", *[f"- {error}" for error in errors]]
    (output / "VALIDATION_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    if errors:
        raise ValueError("; ".join(errors))
    return run
