import json
from pathlib import Path

import pytest

from fr24 import satim_engine
from fr24.calibration.models import LayerCalibrationResult, read_json, write_json


def _manifest(tmp_path: Path, inputs: dict, options: dict | None = None) -> satim_engine.SATIMEngineManifest:
    path = tmp_path / "satim_manifest.json"
    payload = {
        "schema_version": "satim.engine.input.v1",
        "run_id": "test_run",
        "input_profile": "fr24_screenshot_batch",
        "inputs": inputs,
        "options": options or {"export_legacy_readiness": True},
        "outputs": {"run_dir": str(tmp_path / "out")},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return satim_engine.load_manifest(path)


def _ready(layer: str, **metrics):
    return LayerCalibrationResult(layer=layer, status="READY", metrics=metrics).to_dict()


def test_minimal_input_writes_layer_reports_and_marks_l3_missing(tmp_path):
    screenshots = tmp_path / "screenshots"
    screenshots.mkdir()
    manifest = _manifest(tmp_path, {"screenshots_dir": str(screenshots)})

    summary = satim_engine.run_satim_engine(manifest, tmp_path / "out")
    report = read_json(tmp_path / "out" / "calibration_report.json")

    assert summary["status"] == "DEGRADED"
    assert report["layers"]["L3_vision_ocr"]["status"] == "MISSING"
    assert (tmp_path / "out" / "layers" / "l1_ui_segmenter.json").exists()
    assert (tmp_path / "out" / "layers" / "l2_route_extractor.json").exists()
    assert (tmp_path / "out" / "legacy_readiness.json").exists()


def test_full_manifest_reaches_report_merge(monkeypatch, tmp_path):
    screenshots = tmp_path / "screenshots"
    blanks = tmp_path / "blanks"
    screenshots.mkdir()
    blanks.mkdir()
    ground_truth = tmp_path / "ground_truth.csv"
    predictions = tmp_path / "predictions.json"
    fr24_csv = tmp_path / "fr24_export.csv"
    l5_csv = tmp_path / "l5_candidates.csv"
    ground_truth.write_text("image_path,callsign\n", encoding="utf-8")
    predictions.write_text("{}", encoding="utf-8")
    fr24_csv.write_text("registration,callsign,operator,aircraft_type\n", encoding="utf-8")
    l5_csv.write_text("straight_boundary_score,radiometric_discontinuity_score\n", encoding="utf-8")

    monkeypatch.setattr(satim_engine, "calibrate_l1", lambda *_args, **_kwargs: _ready("L1_ui_segmenter", image_count=1))
    monkeypatch.setattr(satim_engine, "calibrate_l2", lambda *_args, **_kwargs: _ready("L2_route_extractor", image_count=1))
    monkeypatch.setattr(satim_engine, "calibrate_l3", lambda *_args, **_kwargs: _ready("L3_vision_ocr", record_count=1))
    monkeypatch.setattr(satim_engine, "calibrate_l4", lambda *_args, **_kwargs: _ready("L4_aircraft_intelligence", record_count=1))
    monkeypatch.setattr(satim_engine, "calibrate_l5", lambda *_args, **_kwargs: _ready("L5_tile_seam_shadow", candidate_count=1))

    manifest = _manifest(
        tmp_path,
        {
            "screenshots_dir": str(screenshots),
            "blank_screenshots_dir": str(blanks),
            "ground_truth_csv": str(ground_truth),
            "predictions_json": str(predictions),
            "fr24_csv": str(fr24_csv),
            "l5_candidates_csv": str(l5_csv),
        },
    )

    summary = satim_engine.run_satim_engine(manifest, tmp_path / "out")
    report = read_json(tmp_path / "out" / "calibration_report.json")

    assert summary["status"] == "READY_FOR_BATCH_ANALYSIS"
    assert report["overall_status"] == "READY_FOR_BATCH_ANALYSIS"
    assert set(report["layers"]) == {
        "L1_ui_segmenter",
        "L2_route_extractor",
        "L3_vision_ocr",
        "L4_aircraft_intelligence",
        "L5_tile_seam_shadow",
    }


def test_missing_advisory_layers_are_partial_not_blocking(monkeypatch, tmp_path):
    screenshots = tmp_path / "screenshots"
    screenshots.mkdir()
    ground_truth = tmp_path / "ground_truth.csv"
    predictions = tmp_path / "predictions.json"
    ground_truth.write_text("image_path,callsign\n", encoding="utf-8")
    predictions.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(satim_engine, "calibrate_l1", lambda *_args, **_kwargs: _ready("L1_ui_segmenter"))
    monkeypatch.setattr(satim_engine, "calibrate_l2", lambda *_args, **_kwargs: _ready("L2_route_extractor"))
    monkeypatch.setattr(satim_engine, "calibrate_l3", lambda *_args, **_kwargs: _ready("L3_vision_ocr", record_count=1))

    manifest = _manifest(
        tmp_path,
        {
            "screenshots_dir": str(screenshots),
            "ground_truth_csv": str(ground_truth),
            "predictions_json": str(predictions),
        },
    )

    summary = satim_engine.run_satim_engine(manifest, tmp_path / "out")
    report = read_json(tmp_path / "out" / "calibration_report.json")

    assert summary["status"] == "PARTIAL"
    assert summary["blocking_gaps"] == []
    assert report["layers"]["L4_aircraft_intelligence"]["status"] == "MISSING"
    assert report["layers"]["L5_tile_seam_shadow"]["status"] == "MISSING"


def test_invalid_manifest_schema_fails(tmp_path):
    manifest_path = tmp_path / "satim_manifest.json"
    manifest_path.write_text(json.dumps({"run_id": "bad", "inputs": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        satim_engine.load_manifest(manifest_path)


def test_calibration_set_validator_writes_packet_result(tmp_path):
    screenshots = tmp_path / "screenshots"
    calibration_set = tmp_path / "calibration_set"
    screenshots.mkdir()
    calibration_set.mkdir()
    manifest = _manifest(
        tmp_path,
        {
            "screenshots_dir": str(screenshots),
            "calibration_set_dir": str(calibration_set),
        },
    )

    satim_engine.run_satim_engine(manifest, tmp_path / "out")
    packet = read_json(tmp_path / "out" / "calibration_set_validation.json")

    assert packet["validation"]["status"] == "FAIL"
    assert packet["validation"]["errors"]


def test_l2_malformed_image_degrades_instead_of_crashing(tmp_path):
    screenshots = tmp_path / "screenshots"
    screenshots.mkdir()
    (screenshots / "corrupt.png").write_bytes(b"not a real png")
    manifest = _manifest(tmp_path, {"screenshots_dir": str(screenshots)})

    summary = satim_engine.run_satim_engine(manifest, tmp_path / "out")
    report = read_json(tmp_path / "out" / "calibration_report.json")

    l2 = report["layers"]["L2_route_extractor"]
    assert l2["status"] == "DEGRADED"
    assert l2["findings"][0]["error_type"] == "UnidentifiedImageError"
    assert summary["status"] == "DEGRADED"


def test_l5_disabled_by_operator_does_not_block_batch_ready(monkeypatch, tmp_path):
    screenshots = tmp_path / "screenshots"
    ground_truth = tmp_path / "ground_truth.csv"
    predictions = tmp_path / "predictions.json"
    fr24_csv = tmp_path / "fr24_export.csv"
    screenshots.mkdir()
    ground_truth.write_text("image_path,callsign\n", encoding="utf-8")
    predictions.write_text("{}", encoding="utf-8")
    fr24_csv.write_text("registration,callsign,operator,aircraft_type\n", encoding="utf-8")

    monkeypatch.setattr(satim_engine, "calibrate_l1", lambda *_args, **_kwargs: _ready("L1_ui_segmenter"))
    monkeypatch.setattr(satim_engine, "calibrate_l2", lambda *_args, **_kwargs: _ready("L2_route_extractor"))
    monkeypatch.setattr(satim_engine, "calibrate_l3", lambda *_args, **_kwargs: _ready("L3_vision_ocr", record_count=1))
    monkeypatch.setattr(satim_engine, "calibrate_l4", lambda *_args, **_kwargs: _ready("L4_aircraft_intelligence", record_count=1))

    manifest = _manifest(
        tmp_path,
        {
            "screenshots_dir": str(screenshots),
            "ground_truth_csv": str(ground_truth),
            "predictions_json": str(predictions),
            "fr24_csv": str(fr24_csv),
        },
        options={"include_l5": False, "export_legacy_readiness": True},
    )

    summary = satim_engine.run_satim_engine(manifest, tmp_path / "out")
    report = read_json(tmp_path / "out" / "calibration_report.json")

    assert summary["status"] == "READY_FOR_BATCH_ANALYSIS"
    assert summary["blocking_gaps"] == []
    assert report["layers"]["L5_tile_seam_shadow"]["status"] == "READY"
    assert report["layers"]["L5_tile_seam_shadow"]["metrics"]["skipped_by_operator"] is True


def test_autodetect_inputs_standard_names(tmp_path):
    root = tmp_path / "input_root"
    (root / "screenshots").mkdir(parents=True)
    (root / "blanks").mkdir()
    (root / "ground_truth.csv").write_text("image_path\n", encoding="utf-8")
    (root / "predictions.json").write_text("{}", encoding="utf-8")
    (root / "fr24_export.csv").write_text("registration\n", encoding="utf-8")
    (root / "l5_candidates.csv").write_text("straight_boundary_score\n", encoding="utf-8")

    detected = satim_engine.autodetect_inputs(root)

    assert detected["screenshots_dir"] == root / "screenshots"
    assert detected["blank_screenshots_dir"] == root / "blanks"
    assert detected["ground_truth_csv"] == root / "ground_truth.csv"
    assert detected["predictions_json"] == root / "predictions.json"
    assert detected["fr24_csv"] == root / "fr24_export.csv"
    assert detected["l5_candidates_csv"] == root / "l5_candidates.csv"
