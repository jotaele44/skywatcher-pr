from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image, ImageDraw

from fr24_image_skill.orchestrator import (
    AnalysisMode,
    FindingDisposition,
    StageState,
    _artifact_candidates,
    _stage_2,
    _write_adjudication_ledgers,
)


def _frame(path: Path, frame_id: str = "FRAME-000001") -> dict[str, object]:
    return {"frame_id": frame_id, "path": str(path), "source_page": 1}


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_zero_finding_ledgers_are_valid(tmp_path: Path) -> None:
    image = tmp_path / "flat.png"
    Image.new("RGB", (120, 100), "gray").save(image)
    stage = _stage_2([_frame(image)], tmp_path, AnalysisMode.STANDARD, StageState("s1", frozen=True))
    assert stage.frozen
    assert _read(tmp_path / "stage_2" / "STAGE_2_ARTIFACT_LEDGER.csv") == []
    contradiction_count, review_count = _write_adjudication_ledgers(tmp_path)
    assert contradiction_count == 0
    assert review_count == 0


def test_single_finding_has_contradiction_and_review_rows(tmp_path: Path) -> None:
    stage_dir = tmp_path / "stage_2"
    stage_dir.mkdir()
    fields = ["finding_id", "frame_id", "class", "pixel_bbox", "confidence", "status"]
    with (stage_dir / "STAGE_2_ARTIFACT_LEDGER.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"finding_id": "SATIM-000001", "frame_id": "FRAME-000001", "class": "POSSIBLE_TILE_SEAM", "pixel_bbox": "[]", "confidence": "0.7", "status": "candidate"})
    contradiction_count, review_count = _write_adjudication_ledgers(tmp_path)
    assert contradiction_count == 1
    assert review_count == 1
    contradiction = _read(tmp_path / "CONTRADICTION_LEDGER.csv")[0]
    review = _read(tmp_path / "MANUAL_REVIEW_QUEUE.csv")[0]
    assert contradiction["finding_id"] == "SATIM-000001"
    assert contradiction["disposition"] == FindingDisposition.NOT_ADJUDICATED.value
    assert review["finding_id"] == "SATIM-000001"


def test_ui_boundary_is_suppressed(tmp_path: Path) -> None:
    image = tmp_path / "ui-edge.png"
    canvas = Image.new("RGB", (200, 120), "white")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 5, 119), fill="black")
    canvas.save(image)
    findings = _artifact_candidates(image, "FRAME-000001", [0, 0, 200, 120])
    assert all(row["class"] != "POSSIBLE_TILE_SEAM" for row in findings)


def test_multi_frame_repeat_group_and_deterministic_order(tmp_path: Path) -> None:
    frames = []
    for index in (2, 1):
        image = tmp_path / f"frame-{index}.png"
        canvas = Image.new("RGB", (200, 120), "white")
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((98, 0, 102, 119), fill="black")
        canvas.save(image)
        frames.append(_frame(image, f"FRAME-{index:06d}"))
    _stage_2(frames, tmp_path, AnalysisMode.STANDARD, StageState("s1", frozen=True))
    findings = _read(tmp_path / "stage_2" / "STAGE_2_ARTIFACT_LEDGER.csv")
    assert findings
    assert all(row["repeat_view_cluster_id"] == "SOURCE_SEQUENCE_001" for row in findings)
    _write_adjudication_ledgers(tmp_path)
    rows = _read(tmp_path / "CONTRADICTION_LEDGER.csv")
    assert [row["finding_id"] for row in rows] == sorted(row["finding_id"] for row in rows)
