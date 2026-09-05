from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from skywatcher.evidence_adapters import materialize_visuals
from skywatcher.evidence_router import inspect_path, merge_manifests

JPEG = b"\xff\xd8\xff\xdbskywatcher-adapter-fixture\xff\xd9"


def test_native_image_materialization_preserves_bytes(tmp_path: Path) -> None:
    image = tmp_path / "capture.jpg"
    image.write_bytes(JPEG)
    manifest = inspect_path(image)
    outputs = materialize_visuals(manifest, tmp_path / "out")
    assert len(outputs) == 1
    assert outputs[0].state == "PASS"
    assert outputs[0].output_sha256 == hashlib.sha256(JPEG).hexdigest()
    assert Path(outputs[0].output_path or "").read_bytes() == JPEG


def test_zip_image_member_materialization_preserves_member_bytes(tmp_path: Path) -> None:
    archive = tmp_path / "capture.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("nested/capture.jpg", JPEG)
    manifest = inspect_path(archive)
    outputs = materialize_visuals(manifest, tmp_path / "out")
    assert len(outputs) == 1
    assert outputs[0].state == "PASS"
    assert outputs[0].source_member == "nested/capture.jpg"
    assert Path(outputs[0].output_path or "").read_bytes() == JPEG


def test_pdf_page_materialization_is_derived_not_source_byte_identity(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    pdf = tmp_path / "capture.pdf"
    document = fitz.open()
    page = document.new_page(width=200, height=100)
    page.insert_text((20, 50), "N5854Z FR24 screenshot fixture")
    document.save(pdf)
    document.close()

    manifest = inspect_path(pdf)
    assert len(manifest.items) == 1
    assert manifest.items[0].sha256 is None
    outputs = materialize_visuals(manifest, tmp_path / "out")
    assert len(outputs) == 1
    output = outputs[0]
    assert output.state == "PASS"
    assert output.adapter == "pymupdf_page_render"
    assert output.output_sha256 is not None
    assert output.output_sha256 != manifest.source_sha256
    assert output.reason and "not source/PDF/page byte identity" in output.reason


def test_mixed_batch_materializes_every_visual_but_not_structured_data(tmp_path: Path) -> None:
    image = tmp_path / "one.jpg"
    image.write_bytes(JPEG)
    data = tmp_path / "track.json"
    data.write_text('{"registration":"N5854Z"}', encoding="utf-8")
    archive = tmp_path / "two.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("two.jpg", JPEG + b"2")

    manifest = merge_manifests([inspect_path(image), inspect_path(data), inspect_path(archive)])
    outputs = materialize_visuals(manifest, tmp_path / "out")
    assert len(outputs) == 2
    assert {row.state for row in outputs} == {"PASS"}
    assert len({row.manifestation_id for row in outputs}) == 2
