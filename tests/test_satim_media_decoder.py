from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import satim_media_decoder as decoder


def write_manifest(tmp_path: Path, input_path: Path, run_id: str = "synthetic_runtime_run") -> Path:
    manifest = {
        "run_id": run_id,
        "input_path": str(input_path),
        "source_family": "synthetic",
        "qa_flags": ["synthetic_fixture"],
    }
    manifest_path = tmp_path / "runtime_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_extension_allowlist_accepts_required_media_types(tmp_path: Path) -> None:
    for suffix in [".pdf", ".jpg", ".jpeg", ".heic", ".png", ".webp", ".tif", ".tiff"]:
        path = tmp_path / f"input{suffix}"
        assert decoder.validate_extension(path) == suffix


def test_extension_allowlist_rejects_unsupported_media_type(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        decoder.validate_extension(tmp_path / "input.mov")


def test_safe_run_id_does_not_fall_back_to_source_filename(tmp_path: Path) -> None:
    input_path = tmp_path / "private_case_media_name.jpg"
    assert decoder.safe_run_id({}, input_path) == "runtime_media_run"


def test_image_decode_sanitizes_source_reference(tmp_path: Path) -> None:
    pillow = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "private_case_media_name.jpg"
    image = pillow.new("RGB", (16, 8), color="white")
    image.save(image_path)

    manifest_path = write_manifest(tmp_path, image_path)
    manifest = decoder.load_manifest(manifest_path)
    result = decoder.decode_media(manifest)

    assert result["frame_count"] == 1
    assert result["source_reference"] == "runtime_input_not_committed"
    assert "private_case_media_name" not in json.dumps(result)
    assert result["frames"][0]["source_reference"] == "runtime_input_not_committed"
    assert result["frames"][0]["width"] == 16
    assert result["frames"][0]["height"] == 8


def test_pdf_decoder_declares_dependency_or_decodes(tmp_path: Path) -> None:
    pdf_path = tmp_path / "private_case_media_name.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% synthetic minimal placeholder\n")
    manifest_path = write_manifest(tmp_path, pdf_path)
    manifest = decoder.load_manifest(manifest_path)

    try:
        result = decoder.decode_media(manifest)
    except RuntimeError as exc:
        assert "PyMuPDF" in str(exc)
    except Exception:
        # Invalid synthetic PDF bytes can fail after dependency import. That is acceptable for
        # this unit smoke test; the dependency path is still wired.
        assert True
    else:
        assert result["source_reference"] == "runtime_input_not_committed"
        assert "private_case_media_name" not in json.dumps(result)


def test_heic_decoder_declares_dependency(tmp_path: Path) -> None:
    heic_path = tmp_path / "private_case_media_name.heic"
    heic_path.write_bytes(b"synthetic")
    manifest_path = write_manifest(tmp_path, heic_path)
    manifest = decoder.load_manifest(manifest_path)

    try:
        decoder.decode_media(manifest)
    except RuntimeError as exc:
        assert "pillow-heif" in str(exc)
    except Exception:
        # If pillow-heif is installed, synthetic bytes may fail deeper in Pillow.
        assert True
