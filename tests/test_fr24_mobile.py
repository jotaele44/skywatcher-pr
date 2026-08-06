from __future__ import annotations

import importlib.util
import json
import struct
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "mobile" / "fr24" / "analyze_fr24_mobile.py"
SPEC = importlib.util.spec_from_file_location("analyze_fr24_mobile", MODULE_PATH)
assert SPEC and SPEC.loader
mobile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mobile)


def write_png(path: Path, width: int = 1170, height: int = 2532) -> None:
    # Header inspection is intentionally bounded; a complete pixel stream is not
    # required to test custody and dimension handling.
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
    )


def manifest(run_id: str = "run-123") -> dict:
    return {
        "schema_version": mobile.SCHEMA_VERSION,
        "run_id": run_id,
        "received_at": "2026-08-06T17:41:00.000Z",
    }


def test_png_intake_is_provisional_and_hash_bound(tmp_path: Path) -> None:
    source = tmp_path / "source_image"
    write_png(source)
    result = mobile.result_for(source, manifest())

    assert result["run_id"] == "run-123"
    assert result["source"]["media_type"] == "image/png"
    assert len(result["source"]["sha256"]) == 64
    assert result["image"] == {"width": 1170, "height": 2532, "orientation": "portrait"}
    assert result["classification"]["status"] == "provisional"
    assert result["classification"]["is_fr24"] == "unresolved"
    assert result["observations"] == []
    assert "desktop_rlsm_parity" in result["unresolved_fields"]
    assert result["processing"]["network_used"] is False


def test_non_image_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "source_image"
    source.write_text("not an image", encoding="utf-8")
    with pytest.raises(mobile.MobileAnalysisError, match="unsupported_image_format"):
        mobile.result_for(source, manifest())


def test_small_image_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source_image"
    write_png(source, 100, 100)
    with pytest.raises(mobile.MobileAnalysisError, match="image_too_small"):
        mobile.result_for(source, manifest())


def test_manifest_requires_exact_schema(tmp_path: Path) -> None:
    path = tmp_path / "input_manifest.json"
    path.write_text(json.dumps({**manifest(), "schema_version": "wrong"}), encoding="utf-8")
    with pytest.raises(mobile.MobileAnalysisError, match="unsupported_schema_version"):
        mobile.load_manifest(path)


def test_main_writes_structured_error(tmp_path: Path) -> None:
    source = tmp_path / "source_image"
    source.write_text("bad", encoding="utf-8")
    input_manifest = tmp_path / "input_manifest.json"
    input_manifest.write_text(json.dumps(manifest()), encoding="utf-8")
    output = tmp_path / "result.json"

    exit_code = mobile.main(
        ["--input", str(source), "--manifest", str(input_manifest), "--output", str(output)]
    )
    result = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert result["status"] == "error"
    assert result["error"]["code"] == "unsupported_image_format"
    assert result["observations"] == []
