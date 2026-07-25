from __future__ import annotations

import json
from pathlib import Path

import pytest

from fr24_image_skill.orchestrator import AnalysisMode, StageState, _correlate, _stage_2, inventory_sources, run_analysis


def _tiny_png(path: Path) -> None:
    # Valid 1x1 transparent PNG.
    path.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c6360000000020001e221bc330000000049454e44ae426082"
        )
    )


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


def test_deterministic_run_id_and_time_separation(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    _tiny_png(image)
    first_output = tmp_path / "out-1"
    second_output = tmp_path / "out-2"
    first = run_analysis(image, first_output, AnalysisMode.TRIAGE)
    second = run_analysis(image, second_output, AnalysisMode.TRIAGE)
    assert first.run_id == second.run_id
    observation = json.loads((first_output / "stage_1" / "STAGE_1_FLIGHT_OBSERVATION.json").read_text())
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


def test_stage_outputs_are_frozen_before_correlation(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    _tiny_png(image)
    run = run_analysis(image, tmp_path / "out", AnalysisMode.FORENSIC)
    assert run.stage_1.frozen is True
    assert run.stage_2.frozen is True
    assert run.correlation.frozen is True
