from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from PIL import Image

from fr24_image_skill.orchestrator import (
    AnalysisMode,
    StageState,
    _correlate,
    _digest_tree,
    _ocr_regions,
    _stage_2,
    inventory_sources,
    run_analysis,
)


def _tiny_png(path: Path) -> None:
    Image.new("RGB", (32, 32), (20, 40, 60)).save(path)


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
    assert (output / "CONTRADICTION_LEDGER.csv").exists()
    frames = list(csv.DictReader((output / "FRAME_INVENTORY.csv").open()))
    assert len(frames) == 1
    assert all(row["sha256"] for row in frames)


def test_adapter_provenance_is_in_manifest_and_file(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    _tiny_png(image)
    output = tmp_path / "out"
    run_analysis(image, output, AnalysisMode.STANDARD)
    manifest = json.loads((output / "RUN_MANIFEST.json").read_text())
    provenance = json.loads((output / "ADAPTER_PROVENANCE.json").read_text())
    assert len(provenance) == 8
    assert manifest["adapter_provenance"] == provenance
    assert {row["name"] for row in provenance} == {
        "ui_segmenter",
        "region_ocr",
        "rlsm_ocr",
        "flight_fusion",
        "track_vectorizer",
        "affine_georegistration",
        "satim_engine",
        "tile_seam_classifier",
    }


def test_no_intent_or_purpose_inference(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    _tiny_png(image)
    output = tmp_path / "out"
    run_analysis(image, output, AnalysisMode.STANDARD)
    observation = json.loads((output / "stage_1" / "STAGE_1_FLIGHT_OBSERVATION.json").read_text())
    findings = json.loads((output / "stage_2" / "STAGE_2_SATIM_FINDINGS.geojson").read_text())
    assert observation["intent_assessment"] == "not_assessed"
    assert findings["properties"]["facility_purpose_inference"] is False
    # ADR v2.1 A1 opened a bounded facility-function channel. It is reported
    # explicitly so a consumer can tell "no assessment was made" from "the field
    # predates the channel", and it stays off for artifact-candidate-only output.
    assert findings["properties"]["function_assessment_enabled"] is False


def test_function_assessment_cannot_be_emitted_without_a_confidence_record() -> None:
    """ADR v2.1 A1: the bounded channel is only bounded if the record is mandatory.

    Checked against the schema document itself rather than through a validator, so
    the guarantee holds without adding a jsonschema dependency here — the same
    approach tests/test_schema_satim_fpim_corrim_contracts.py takes.
    """
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "skills/skywatcher-fr24-image-analysis/schemas/satim_finding.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    # Unbounded purpose inference is still prohibited outright.
    assert schema["properties"]["purpose_inference"]["const"] is False

    assessment = schema["properties"]["function_assessment"]
    assert assessment["additionalProperties"] is False

    # Every ADR section 5.3 confidence field is required, so a bare class label with
    # no method, scope, version, or supporting observations cannot validate.
    required = set(assessment["required"])
    assert {
        "class",
        "confidence",
        "confidence_method",
        "confidence_scope",
        "method_version",
        "supporting_observation_ids",
        "limitations",
        "interpretation_restriction",
    } <= required

    assert assessment["properties"]["supporting_observation_ids"]["minItems"] == 1
    assert set(assessment["properties"]["class"]["enum"]) == {
        "DUAL_USE_FUNCTION_CANDIDATE",
        "SINGLE_USE_CIVILIAN_CANDIDATE",
        "UNRESOLVED",
    }


def test_ocr_degrades_when_tesseract_binary_is_absent(tmp_path: Path, monkeypatch) -> None:
    """pytesseract installed but the tesseract BINARY missing must not crash.

    The two are installed separately and pytesseract is not declared in any
    manifest here, so this combination is a normal state. Importing the package
    succeeds; it is image_to_string that raises TesseractNotFoundError at call
    time. Before the probe in _ocr_regions, that escaped and took out every test
    touching the OCR path.
    """
    pytesseract = pytest.importorskip("pytesseract")
    frame = tmp_path / "frame.png"
    _tiny_png(frame)

    def _no_binary(*_args, **_kwargs):
        raise pytesseract.TesseractNotFoundError()

    # Fail the way a missing binary does, from both the probe and the call, so
    # the test still holds if the probe is ever moved or removed.
    monkeypatch.setattr(pytesseract, "get_tesseract_version", _no_binary)
    monkeypatch.setattr(pytesseract, "image_to_string", _no_binary)

    rows = _ocr_regions(frame, "frame-1")

    assert [r["status"] for r in rows] == ["dependency_unavailable"]
    assert rows[0]["method"] == "unavailable"
    assert rows[0]["value"] == ""
