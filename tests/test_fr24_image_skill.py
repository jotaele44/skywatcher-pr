from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from fr24_image_skill.orchestrator import (
    AnalysisMode,
    StageState,
    _correlate,
    _digest_tree,
    _stage_2,
    inventory_sources,
    run_analysis,
)


def _tiny_png(path: Path) -> None:
    path.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6360000000020001e221bc330000000049454e44ae426082"
    ))


def test_inventory_has_full_hash_coverage(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    _tiny_png(image)
    records = inventory_sources(tmp_path)
    assert len(records) == 1
    assert len(records[0].sha256) == 64
    assert records[0].status == "accounted"


def test_stage_2_requires_frozen_stage_1(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Stage 1 must be frozen"):
        _stage_2([], tmp_path, AnalysisMode.STANDARD, StageState(name="stage_1"))


def test_correlation_requires_both_frozen(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Both stages must be frozen"):
        _correlate(tmp_path, StageState(name="one", frozen=True), StageState(name="two", frozen=False))


def test_deterministic_run_id_and_normalized_digest(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    _tiny_png(image)
    first_output = tmp_path / "out-1"
    second_output = tmp_path / "out-2"
    first = run_analysis(image, first_output, AnalysisMode.TRIAGE)
    second = run_analysis(image, second_output, AnalysisMode.TRIAGE)
    assert first.run_id == second.run_id
    assert first.deterministic_digest == second.deterministic_digest
    assert _digest_tree(first_output) == _digest_tree(second_output)


def test_time_fields_are_separate(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    _tiny_png(image)
    output = tmp_path / "out"
    run_analysis(image, output, AnalysisMode.TRIAGE)
    observation = json.loads((output / "stage_1" / "STAGE_1_FLIGHT_OBSERVATION.json").read_text())
    assert observation["time_fields_separate"] is True
    assert observation["device_capture_time"] is None
    assert observation["fr24_replay_time"] is None


def test_no_fixed_bounds_promotion(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    _tiny_png(image)
    output = tmp_path / "out"
    run_analysis(image, output, AnalysisMode.STANDARD)
    track = json.loads((output / "stage_1" / "STAGE_1_TRACK_REGISTERED.geojson").read_text())
    assert track["properties"]["fixed_bounds_promotion"] is False
    assert track["properties"]["status"] == "not_registered"
    assert "multi-anchor" in track["properties"]["reason"]


def test_stage_outputs_and_real_ledgers(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    _tiny_png(image)
    output = tmp_path / "out"
    run = run_analysis(image, output, AnalysisMode.FORENSIC)
    assert run.stage_1.frozen and run.stage_2.frozen and run.correlation.frozen
    assert (output / "stage_1" / "STAGE_1_SEGMENT_LEDGER.csv").exists()
    assert (output / "stage_2" / "STAGE_2_REPEAT_VIEW_MATRIX.csv").exists()
    frames = list(csv.DictReader((output / "FRAME_INVENTORY.csv").open()))
    assert len(frames) == 1
    assert all(row["sha256"] for row in frames)


def test_no_intent_or_purpose_inference(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    _tiny_png(image)
    output = tmp_path / "out"
    run_analysis(image, output, AnalysisMode.STANDARD)
    observation = json.loads((output / "stage_1" / "STAGE_1_FLIGHT_OBSERVATION.json").read_text())
    findings = json.loads((output / "stage_2" / "STAGE_2_SATIM_FINDINGS.geojson").read_text())
    assert observation["intent_assessment"] == "not_assessed"
    assert findings["properties"]["facility_purpose_inference"] is False
