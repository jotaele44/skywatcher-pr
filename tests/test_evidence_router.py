from __future__ import annotations

import json
import zipfile
from pathlib import Path

from skywatcher.evidence_router import (
    build_route_plan,
    inspect_path,
    merge_manifests,
    route_paths,
)

MINIMAL_JPEG = b"\xff\xd8\xff\xdbskywatcher-fixture\xff\xd9"
MINIMAL_PDF = b"%PDF-1.4\n1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>endobj\n%%EOF\n"


def _skill_ids(plan) -> set[str]:
    return {str(row["skill_id"]) for row in plan.skills}


def test_native_jpeg_routes_visual_stack(tmp_path: Path) -> None:
    image = tmp_path / "capture.jpg"
    image.write_bytes(MINIMAL_JPEG)
    plan = route_paths([image])
    assert plan.gates["SOURCE_FREEZE"] == "PASS"
    assert plan.gates["DENOMINATOR"] == "PASS"
    assert plan.gates["VISUAL_ROUTING"] == "PASS"
    assert {"RLSM", "FPIM", "CORRIM", "SATIM", "TIMELINE", "PATTERN"} <= _skill_ids(plan)


def test_zip_member_preserves_container_manifestation_and_payload_hash(tmp_path: Path) -> None:
    archive = tmp_path / "capture.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("nested/capture.jpg", MINIMAL_JPEG)
    manifest = inspect_path(archive)
    assert manifest.container_kind == "archive"
    assert len(manifest.items) == 1
    item = manifest.items[0]
    assert item.media_kind == "archive_image_member"
    assert item.member_path == "nested/capture.jpg"
    assert item.sha256 is not None


def test_pdf_page_is_visual_manifestation_but_not_byte_identity(tmp_path: Path) -> None:
    pdf = tmp_path / "capture.pdf"
    pdf.write_bytes(MINIMAL_PDF)
    manifest = inspect_path(pdf)
    assert manifest.container_kind == "pdf"
    assert not manifest.unresolved
    assert len(manifest.items) == 1
    page = manifest.items[0]
    assert page.media_kind == "pdf_page_visual"
    assert page.page_number == 1
    assert page.sha256 is None
    assert page.status == "PROVISIONAL"


def test_jpeg_pdf_page_and_zip_member_have_equivalent_visual_skill_routing(tmp_path: Path) -> None:
    image = tmp_path / "capture.jpg"
    image.write_bytes(MINIMAL_JPEG)
    pdf = tmp_path / "capture.pdf"
    pdf.write_bytes(MINIMAL_PDF)
    archive = tmp_path / "capture.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("capture.jpg", MINIMAL_JPEG)

    native = build_route_plan(inspect_path(image))
    pdf_plan = build_route_plan(inspect_path(pdf))
    zip_plan = build_route_plan(inspect_path(archive))

    required = {"RLSM", "FPIM", "CORRIM", "SATIM", "TIMELINE", "PATTERN"}
    assert required <= _skill_ids(native)
    assert required <= _skill_ids(pdf_plan)
    assert required <= _skill_ids(zip_plan)
    assert native.manifest.container_kind != pdf_plan.manifest.container_kind
    assert pdf_plan.manifest.container_kind != zip_plan.manifest.container_kind
    assert native.manifest.items[0].manifestation_id != zip_plan.manifest.items[0].manifestation_id


def test_mixed_batch_preserves_all_source_manifestations(tmp_path: Path) -> None:
    image = tmp_path / "one.jpg"
    image.write_bytes(MINIMAL_JPEG)
    data = tmp_path / "track.json"
    data.write_text(json.dumps({"registration": "N5854Z"}), encoding="utf-8")
    merged = merge_manifests([inspect_path(image), inspect_path(data)])
    assert merged.container_kind == "mixed_batch"
    assert len(merged.items) == 2
    assert {i.media_kind for i in merged.items} == {"native_image", "structured_event_data"}
    assert build_route_plan(merged).gates["DENOMINATOR"] == "PASS"


def test_duplicate_zip_payloads_are_preserved_not_collapsed(tmp_path: Path) -> None:
    archive = tmp_path / "dupes.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.jpg", MINIMAL_JPEG)
        zf.writestr("b.jpg", MINIMAL_JPEG)
    manifest = inspect_path(archive)
    assert len(manifest.items) == 2
    assert manifest.items[0].sha256 == manifest.items[1].sha256
    assert manifest.items[0].member_path != manifest.items[1].member_path
    assert any(row["class"] == "BYTE" for row in manifest.contradictions)


def test_zero_altitude_and_zero_speed_are_only_safeguards_not_promotions(tmp_path: Path) -> None:
    image = tmp_path / "n5854z.jpg"
    image.write_bytes(MINIMAL_JPEG)
    plan = route_paths([image])
    text = "\n".join(plan.safeguards)
    assert "0 ft must not imply ON_GROUND" in text
    assert "0 mph/track termination must not certify landing" in text
    assert plan.gates["ANALYTICAL_CERTIFICATION"] == "OPEN"


def test_unreadable_or_unsupported_source_fails_closed(tmp_path: Path) -> None:
    unknown = tmp_path / "capture.xyz"
    unknown.write_bytes(b"unknown")
    plan = route_paths([unknown])
    assert plan.gates["DENOMINATOR"] == "BLOCKED"
    assert plan.manifest.unresolved
