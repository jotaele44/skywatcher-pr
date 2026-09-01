from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from fr24_image_skill import orchestrator
from fr24_image_skill.orchestrator import (
    AnalysisMode,
    SourceRecord,
    _artifact_candidates,
    _render_sources,
    _stage_1,
    _vectorize,
)


def test_native_vectorizer_preserves_sampled_route_coordinates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @dataclass
    class NativeResult:
        path_shape: str = "linear"
        has_loop: int = 0
        has_orbit: int = 0
        has_gap: int = 0
        track_length_px: float = 42.0
        bbox: tuple[int, int, int, int] = (1, 2, 40, 3)
        confidence: float = 0.6
        component_count: int = 1
        sampled_points: list[tuple[int, int]] | None = None

    native = NativeResult(sampled_points=[(1, 2), (20, 2), (41, 2)])
    monkeypatch.setitem(
        sys.modules,
        "fr24.track_vectorizer",
        SimpleNamespace(vectorize_image=lambda path: native),
    )
    image = tmp_path / "route.png"
    Image.new("RGB", (64, 32), "gray").save(image)

    result = _vectorize(image)

    assert result is not None
    assert result["method"] == "fr24.track_vectorizer"
    assert result["sampled_points"] == [(1, 2), (20, 2), (41, 2)]


def test_overlay_route_is_masked_before_artifact_classification(tmp_path: Path) -> None:
    image = tmp_path / "overlay.png"
    canvas = Image.new("RGB", (200, 120), (110, 110, 110))
    ImageDraw.Draw(canvas).line((100, 5, 100, 115), fill=(0, 255, 0), width=3)
    canvas.save(image)
    overlay_points = [[100, y] for y in range(5, 116)]

    findings = _artifact_candidates(
        image,
        "FRAME-000001",
        [0, 0, 200, 120],
        overlay_points=overlay_points,
    )

    assert all(row["class"] != "POSSIBLE_TILE_SEAM" for row in findings)


def test_stage_1_analyzes_every_rendered_pdf_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = []
    frames = []
    for index, page in enumerate((6, 9, 12), 1):
        path = tmp_path / f"page-{page}.png"
        Image.new("RGB", (32, 32), "gray").save(path)
        paths.append(path)
        frames.append({"frame_id": f"FRAME-{index:06d}", "path": str(path), "source_page": page})

    ocr_calls: list[str] = []
    vector_calls: list[str] = []
    monkeypatch.setattr(
        orchestrator,
        "_segment_frame",
        lambda path: {"map_bbox": [0, 0, 32, 32], "method": "test", "confidence": 1.0},
    )
    monkeypatch.setattr(
        orchestrator,
        "_ocr_regions",
        lambda path, frame_id: ocr_calls.append(frame_id) or [],
    )
    monkeypatch.setattr(
        orchestrator,
        "_vectorize",
        lambda path: vector_calls.append(Path(path).name) or None,
    )

    _stage_1(frames, tmp_path / "out", AnalysisMode.STANDARD)

    assert ocr_calls == [frame["frame_id"] for frame in frames]
    assert vector_calls == [path.name for path in paths]


def test_dark_surface_threshold_is_reachable(tmp_path: Path) -> None:
    image = tmp_path / "dark.png"
    Image.new("RGB", (120, 100), "black").save(image)

    findings = _artifact_candidates(image, "FRAME-000001", [0, 0, 120, 100])

    assert any(row["class"] == "DARK_SURFACE_POLYGON" for row in findings)


def test_pdf_rendering_falls_back_to_pymupdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fitz = pytest.importorskip("fitz")
    pdf = tmp_path / "fixture.pdf"
    with fitz.open() as document:
        document.new_page()
        document.new_page()
        document.save(pdf)
    source = SourceRecord(
        "SRC-00001",
        str(pdf),
        "image_pdf",
        orchestrator.sha256_file(pdf),
        pdf.stat().st_size,
    )
    monkeypatch.setattr(orchestrator.shutil, "which", lambda command: None)

    frames = _render_sources([source], tmp_path / "out")

    assert len(frames) == 2
    assert all(frame["extraction_method"] == "pymupdf-72dpi-fallback" for frame in frames)


def test_observation_schema_version_matches_shipped_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    image = tmp_path / "frame.png"
    Image.new("RGB", (32, 32), "gray").save(image)
    frame = {"frame_id": "FRAME-000001", "path": str(image), "source_page": 1}
    monkeypatch.setattr(
        orchestrator,
        "_segment_frame",
        lambda path: {"map_bbox": [0, 0, 32, 32], "method": "test", "confidence": 1.0},
    )
    monkeypatch.setattr(orchestrator, "_ocr_regions", lambda path, frame_id: [])
    monkeypatch.setattr(orchestrator, "_vectorize", lambda path: None)

    output = tmp_path / "out"
    _stage_1([frame], output, AnalysisMode.STANDARD)
    observation = json.loads((output / "stage_1" / "STAGE_1_FLIGHT_OBSERVATION.json").read_text())
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "skywatcher-fr24-image-analysis"
        / "schemas"
        / "flight_observation.schema.json"
    )
    schema = json.loads(schema_path.read_text())

    assert observation["schema_version"] == "0.1.0"
    jsonschema.validate(observation, schema)
