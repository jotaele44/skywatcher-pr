from pathlib import Path

from fr24 import satim_engine
from fr24.calibration.models import LayerCalibrationResult, read_json


def _ready(layer: str):
    return LayerCalibrationResult(layer=layer, status="READY", metrics={}).to_dict()


def test_l2_runtime_error_emits_degraded_layer(monkeypatch, tmp_path: Path):
    screenshots = tmp_path / "screenshots"
    screenshots.mkdir()
    truth = tmp_path / "ground_truth.csv"
    predictions = tmp_path / "predictions.json"
    truth.write_text("image_path,callsign\n", encoding="utf-8")
    predictions.write_text("{}", encoding="utf-8")

    def fail_l2(*_args, **_kwargs):
        raise RuntimeError("Pillow is required to inspect image pixels")

    monkeypatch.setattr(satim_engine, "calibrate_l1", lambda *_args, **_kwargs: _ready("L1_ui_segmenter"))
    monkeypatch.setattr(satim_engine, "calibrate_l2", fail_l2)
    monkeypatch.setattr(satim_engine, "calibrate_l3", lambda *_args, **_kwargs: _ready("L3_vision_ocr"))

    manifest = satim_engine.SATIMEngineManifest(
        schema_version="satim.engine.input.v1",
        run_id="l2_failure",
        input_profile="fr24_screenshot_batch",
        inputs={
            "screenshots_dir": screenshots,
            "ground_truth_csv": truth,
            "predictions_json": predictions,
        },
        options={"export_legacy_readiness": True},
        outputs={"run_dir": tmp_path / "out"},
    )

    summary = satim_engine.run_satim_engine(manifest, tmp_path / "out")
    report = read_json(tmp_path / "out" / "calibration_report.json")

    assert (tmp_path / "out" / "calibration_report.json").exists()
    assert report["layers"]["L2_route_extractor"]["status"] == "DEGRADED"
    assert report["overall_status"] == "DEGRADED"
    assert summary["status"] == "DEGRADED"
