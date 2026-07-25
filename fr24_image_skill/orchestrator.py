from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


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
    created_at_utc: str
    sources: list[SourceRecord]
    stage_1: StageState
    stage_2: StageState
    correlation: StageState
    deterministic_config: dict[str, Any]


SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi"}
SUPPORTED_PDF_SUFFIXES = {".pdf"}
FORBIDDEN_TERMS = {
    "surveillance mission",
    "targeted the site",
    "inspected the site",
    "facility purpose",
    "underground facility",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _iter_inputs(input_path: Path) -> Iterable[Path]:
    if input_path.is_file():
        yield input_path
        return
    if not input_path.is_dir():
        raise FileNotFoundError(input_path)
    for path in sorted(input_path.rglob("*")):
        if path.is_file():
            yield path


def _classify(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return "image"
    if suffix in SUPPORTED_PDF_SUFFIXES:
        return "image_pdf"
    if suffix in SUPPORTED_VIDEO_SUFFIXES:
        return "video"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def inventory_sources(input_path: Path) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for index, path in enumerate(_iter_inputs(input_path), start=1):
        records.append(
            SourceRecord(
                source_id=f"SRC-{index:05d}",
                path=str(path.resolve()),
                media_type=_classify(path),
                sha256=sha256_file(path),
                size_bytes=path.stat().st_size,
            )
        )
    if not records:
        raise ValueError("No input files found")
    return records


def _stable_run_id(sources: list[SourceRecord], mode: AnalysisMode) -> str:
    payload = "|".join([mode.value, *[record.sha256 for record in sources]])
    return "SWFR24-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16].upper()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _render_sources(sources: list[SourceRecord], output_dir: Path) -> list[dict[str, Any]]:
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    frame_index = 0
    for source in sources:
        source_path = Path(source.path)
        if source.media_type == "image":
            frame_index += 1
            target = frames_dir / f"frame-{frame_index:05d}{source_path.suffix.lower()}"
            shutil.copy2(source_path, target)
            frames.append(_frame_record(frame_index, source, target, page=None, extraction="copy"))
        elif source.media_type == "image_pdf":
            rendered = _render_pdf(source_path, frames_dir, frame_index)
            for item in rendered:
                frame_index += 1
                frames.append(_frame_record(frame_index, source, item["path"], page=item["page"], extraction=item["method"]))
        elif source.media_type == "video":
            rendered = _render_video(source_path, frames_dir, frame_index)
            for item in rendered:
                frame_index += 1
                record = _frame_record(frame_index, source, item["path"], page=None, extraction=item["method"])
                record["video_time_s"] = item["video_time_s"]
                frames.append(record)
        else:
            frames.append({"source_id": source.source_id, "status": "unsupported_media", "path": source.path})
    return frames


def _frame_record(index: int, source: SourceRecord, path: Path, page: int | None, extraction: str) -> dict[str, Any]:
    return {
        "frame_id": f"FRAME-{index:06d}",
        "source_id": source.source_id,
        "source_page": page,
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "extraction_method": extraction,
        "status": "accounted",
    }


def _render_pdf(path: Path, frames_dir: Path, offset: int) -> list[dict[str, Any]]:
    prefix = frames_dir / f"pdf-{offset + 1:05d}"
    if shutil.which("pdftoppm"):
        subprocess.run(["pdftoppm", "-png", "-r", "150", str(path), str(prefix)], check=True)
        files = sorted(frames_dir.glob(prefix.name + "-*.png"))
        return [{"path": file, "page": i, "method": "pdftoppm-150dpi"} for i, file in enumerate(files, start=1)]
    return []


def _render_video(path: Path, frames_dir: Path, offset: int) -> list[dict[str, Any]]:
    if not shutil.which("ffmpeg"):
        return []
    pattern = frames_dir / f"video-{offset + 1:05d}-%06d.png"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vf", "fps=1", str(pattern)], check=True)
    files = sorted(frames_dir.glob(f"video-{offset + 1:05d}-*.png"))
    return [{"path": file, "video_time_s": i - 1, "method": "ffmpeg-1fps"} for i, file in enumerate(files, start=1)]


def _optional_adapter(module: str, args: list[str]) -> tuple[bool, str]:
    command = [sys.executable, "-m", module, *args]
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{module}: {exc}"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-1200:]
        return False, f"{module} exited {completed.returncode}: {detail}"
    return True, (completed.stdout or "").strip()[-1200:]


def _stage_1(frames: list[dict[str, Any]], output_dir: Path, mode: AnalysisMode) -> StageState:
    state = StageState(name="flight_evidence_extraction", status="running")
    stage_dir = output_dir / "stage_1"
    stage_dir.mkdir(parents=True, exist_ok=True)

    observation = {
        "schema_version": "0.1.0",
        "status": "screen_derived_unverified",
        "device_capture_time": None,
        "fr24_replay_time": None,
        "time_fields_separate": True,
        "flight_fields": {},
        "frame_ids": [f.get("frame_id") for f in frames if f.get("frame_id")],
        "intent_assessment": "not_assessed",
        "notes": ["No field is promoted without frame-region provenance."],
    }
    observation_path = stage_dir / "STAGE_1_FLIGHT_OBSERVATION.json"
    _write_json(observation_path, observation)

    raw_track = {"type": "FeatureCollection", "features": [], "properties": {"coordinate_space": "pixel"}}
    registered_track = {"type": "FeatureCollection", "features": [], "properties": {"status": "not_registered", "fixed_bounds_promotion": False}}
    _write_json(stage_dir / "STAGE_1_TRACK_RAW.geojson", raw_track)
    _write_json(stage_dir / "STAGE_1_TRACK_REGISTERED.geojson", registered_track)

    _write_csv(stage_dir / "STAGE_1_OCR_LEDGER.csv", ["frame_id", "region", "field", "value", "confidence", "method", "status"], [])
    _write_csv(stage_dir / "STAGE_1_CALIBRATION_LEDGER.csv", ["frame_id", "method", "anchor_count", "rmse_m", "estimated_error_m", "status"], [])

    adapter_plan = [
        ("fr24.ui_segmenter", ["--help"]),
        ("fr24.flight_fusion", ["--help"]),
        ("fr24.track_vectorizer", ["--help"]),
    ]
    for module, args in adapter_plan:
        ok, detail = _optional_adapter(module, args)
        if not ok:
            state.warnings.append(detail)

    state.outputs = [str(path.relative_to(output_dir)) for path in sorted(stage_dir.iterdir())]
    state.status = "complete_with_warnings" if state.warnings else "complete"
    state.frozen = True
    return state


def _stage_2(frames: list[dict[str, Any]], output_dir: Path, mode: AnalysisMode, stage_1: StageState) -> StageState:
    if not stage_1.frozen:
        raise RuntimeError("Stage 1 must be frozen before Stage 2")
    state = StageState(name="satim_imagery_analysis", status="running")
    stage_dir = output_dir / "stage_2"
    stage_dir.mkdir(parents=True, exist_ok=True)

    findings = {
        "type": "FeatureCollection",
        "features": [],
        "properties": {
            "schema_version": "0.1.0",
            "source_status": "screenshot_only",
            "facility_purpose_inference": False,
            "allowed_classes": [
                "UI_OVERLAY", "ROUTE_LINE_CONTAMINATION", "MAP_LABEL", "ZOOM_BLUR",
                "SCREENSHOT_RESAMPLING", "COMPRESSION_ARTIFACT", "TILE_SEAM",
                "POSSIBLE_TILE_SEAM", "RADIOMETRIC_BOUNDARY", "MOSAIC_DATE_BOUNDARY",
                "ORTHORECTIFICATION_MISMATCH", "TERRAIN_SHADOW", "VEGETATION_SHADOW",
                "DARK_SURFACE_POLYGON", "EXPOSED_GROUND", "VEGETATION_BOUNDARY",
                "PERSISTENT_SURFACE_FEATURE", "UNRESOLVED"
            ],
        },
    }
    _write_json(stage_dir / "STAGE_2_SATIM_FINDINGS.geojson", findings)
    _write_csv(stage_dir / "STAGE_2_ARTIFACT_LEDGER.csv", ["finding_id", "frame_id", "class", "pixel_bbox", "confidence", "status", "analyst_note"], [])
    _write_csv(stage_dir / "STAGE_2_REPEAT_VIEW_MATRIX.csv", ["group_id", "frame_id", "zoom_relation", "boundary_persistence", "screen_aligned", "ground_aligned", "status"], [])

    ok, detail = _optional_adapter("fr24.satim_engine", ["--help"])
    if not ok:
        state.warnings.append(detail)
    state.outputs = [str(path.relative_to(output_dir)) for path in sorted(stage_dir.iterdir())]
    state.status = "complete_with_warnings" if state.warnings else "complete"
    state.frozen = True
    return state


def _correlate(output_dir: Path, stage_1: StageState, stage_2: StageState) -> StageState:
    if not stage_1.frozen or not stage_2.frozen:
        raise RuntimeError("Both stages must be frozen before correlation")
    state = StageState(name="post_freeze_correlation", status="running")
    path = output_dir / "CORRELATION_LEDGER.csv"
    _write_csv(path, ["correlation_id", "flight_finding_id", "satim_finding_id", "relationship", "distance_m", "distance_uncertainty_m", "temporal_status", "causal_status", "confidence"], [])
    state.outputs = [path.name]
    state.status = "complete"
    state.frozen = True
    return state


def _validate(run: SkillRun, output_dir: Path, frames: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if len(run.sources) == 0:
        errors.append("No sources accounted")
    if any(not source.sha256 for source in run.sources):
        errors.append("Missing source hash")
    if not run.stage_1.frozen or not run.stage_2.frozen or not run.correlation.frozen:
        errors.append("One or more stages are not frozen")
    if any(frame.get("frame_id") and not frame.get("sha256") for frame in frames):
        errors.append("Missing frame hash")
    searchable = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in output_dir.rglob("*") if path.is_file() and path.suffix.lower() in {".json", ".csv", ".md", ".geojson"}).lower()
    for forbidden in FORBIDDEN_TERMS:
        if forbidden in searchable:
            errors.append(f"Forbidden inference phrase present: {forbidden}")
    return errors


def run_analysis(input_path: str | Path, output_dir: str | Path, mode: AnalysisMode = AnalysisMode.STANDARD) -> SkillRun:
    input_root = Path(input_path).expanduser().resolve()
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    sources = inventory_sources(input_root)
    run_id = _stable_run_id(sources, mode)
    frames = _render_sources(sources, out)

    _write_csv(out / "SOURCE_INVENTORY.csv", ["source_id", "path", "media_type", "sha256", "size_bytes", "status"], [asdict(source) for source in sources])
    (out / "SOURCE_CHECKSUMS.sha256").write_text("".join(f"{source.sha256}  {source.path}\n" for source in sources), encoding="utf-8")
    _write_csv(out / "FRAME_INVENTORY.csv", ["frame_id", "source_id", "source_page", "video_time_s", "path", "sha256", "size_bytes", "extraction_method", "status"], frames)

    stage_1 = _stage_1(frames, out, mode)
    stage_2 = _stage_2(frames, out, mode, stage_1)
    correlation = _correlate(out, stage_1, stage_2)

    run = SkillRun(
        run_id=run_id,
        mode=mode.value,
        input_root=str(input_root),
        output_dir=str(out),
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        sources=sources,
        stage_1=stage_1,
        stage_2=stage_2,
        correlation=correlation,
        deterministic_config={"pdf_dpi": 150, "video_fps": 1, "sort": "lexicographic", "fixed_bounds_promotion": False},
    )
    _write_json(out / "RUN_MANIFEST.json", asdict(run))
    _write_csv(out / "CONTRADICTION_LEDGER.csv", ["contradiction_id", "finding_id", "supporting_frame", "contradicting_frame", "description", "status"], [])
    _write_csv(out / "MANUAL_REVIEW_QUEUE.csv", ["review_id", "stage", "frame_id", "reason", "priority", "status"], [])

    errors = _validate(run, out, frames)
    report = [
        "# Skywatcher FR24 Image Analysis Validation",
        "",
        f"- Run ID: `{run.run_id}`",
        f"- Mode: `{run.mode}`",
        f"- Sources accounted: {len(sources)}",
        f"- Frames accounted: {len([f for f in frames if f.get('frame_id')])}",
        f"- Stage 1 frozen: {stage_1.frozen}",
        f"- Stage 2 frozen: {stage_2.frozen}",
        f"- Correlation frozen: {correlation.frozen}",
        f"- Validation: {'PASS' if not errors else 'FAIL'}",
        "",
        "## Errors",
        *(f"- {error}" for error in errors),
        "",
        "## Warnings",
        *(f"- {warning}" for warning in [*stage_1.warnings, *stage_2.warnings]),
    ]
    (out / "VALIDATION_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    if errors:
        raise ValueError("Validation failed: " + "; ".join(errors))
    return run
