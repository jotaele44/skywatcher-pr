"""Unit tests for the visual-OCR backend extension point.

Pure stdlib — no pandas — so these run in any environment.
"""
from satim_engine.plugins.visual_ocr import extract_visual_metadata


def test_default_is_deterministic_filename_adapter():
    meta = extract_visual_metadata("/tmp/screenshots/FR24_TEST1_2026-01-01.jpg")
    assert meta["ocr_status"] == "FILENAME_ONLY"
    assert meta["text"] == "FR24_TEST1_2026-01-01"
    assert meta["plugin"] == "visual_ocr.default_filename_adapter"
    assert meta["callsign_hint"] is None
    assert meta["timestamp_hint"] is None
    assert meta["tail_hint"] is None
    assert "ocr_error" not in meta


def test_backend_result_merges_over_filename_defaults():
    def fake_backend(path):
        return {
            "text": "N123AB 18:42Z",
            "callsign_hint": "N123AB",
            "timestamp_hint": "18:42Z",
        }

    meta = extract_visual_metadata("/tmp/x/frame.jpg", backend=fake_backend)
    assert meta["text"] == "N123AB 18:42Z"
    assert meta["callsign_hint"] == "N123AB"
    assert meta["timestamp_hint"] == "18:42Z"
    # Backend omitted tail_hint -> canonical field still present, defaulted None.
    assert meta["tail_hint"] is None
    # Backend supplied no plugin/status -> module-default backend labels applied.
    assert meta["plugin"] == "visual_ocr.backend"
    assert meta["ocr_status"] == "OCR_BACKEND"
    # Path provenance is preserved from the filename defaults.
    assert meta["visual_path"] == "/tmp/x/frame.jpg"


def test_backend_may_override_plugin_and_status():
    def labeled_backend(path):
        return {"text": "hi", "plugin": "visual_ocr.tesseract", "ocr_status": "OCR_OK"}

    meta = extract_visual_metadata("/tmp/x/frame.jpg", backend=labeled_backend)
    assert meta["plugin"] == "visual_ocr.tesseract"
    assert meta["ocr_status"] == "OCR_OK"


def test_backend_error_degrades_without_raising():
    def broken_backend(path):
        raise RuntimeError("engine not installed")

    meta = extract_visual_metadata("/tmp/x/frame.jpg", backend=broken_backend)
    assert meta["ocr_status"] == "OCR_BACKEND_ERROR"
    assert "engine not installed" in meta["ocr_error"]
    # Falls back to the filename text so the pipeline still gets a row.
    assert meta["text"] == "frame"
    assert meta["plugin"] == "visual_ocr.default_filename_adapter"
