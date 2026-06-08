import pytest

from fr24_screenshot_model import SourcePlatform, sha256_file
from fr24_screenshot_provenance import (
    ScreenshotProvenanceError,
    build_batch_screenshot_provenance,
    build_screenshot_provenance_from_image_path,
    deterministic_batch_lineage_id,
    infer_source_platform,
)


def test_infer_source_platform_from_fr24_path_keywords():
    assert infer_source_platform("captures/FR24_iOS_frame_001.jpeg") == SourcePlatform.FR24_IOS
    assert infer_source_platform("captures/fr24_android_frame_001.jpeg") == SourcePlatform.FR24_ANDROID
    assert infer_source_platform("captures/fr24_desktop_browser_frame_001.png") == SourcePlatform.FR24_WEB
    assert infer_source_platform("captures/fr24_unknown_frame_001.png") == SourcePlatform.FR24_UNKNOWN
    assert infer_source_platform("captures/random_map_frame_001.png") == SourcePlatform.OTHER


def test_explicit_source_platform_overrides_path_keyword():
    assert infer_source_platform(
        "captures/fr24_ios_frame_001.jpeg",
        explicit=SourcePlatform.FR24_WEB,
    ) == SourcePlatform.FR24_WEB


def test_build_screenshot_provenance_from_image_path(tmp_path):
    image_path = tmp_path / "FR24_iOS_frame_001.jpeg"
    image_path.write_bytes(b"frame-001")

    record = build_screenshot_provenance_from_image_path(image_path)

    assert record.image_path == str(image_path)
    assert record.image_sha256 == sha256_file(image_path)
    assert record.source_platform == SourcePlatform.FR24_IOS
    assert record.screenshot_id.startswith("fr24shot_fr24_ios_")
    assert record.lineage_id == f"lineage_{record.screenshot_id}"
    assert record.metadata["filename"] == "FR24_iOS_frame_001.jpeg"
    assert record.metadata["file_size_bytes"] == len(b"frame-001")
    assert record.parent_lineage_id is None
    assert record.child_lineage_ids == ()


def test_build_screenshot_provenance_allows_parent_lineage_and_metadata(tmp_path):
    image_path = tmp_path / "fr24_web_frame_001.png"
    image_path.write_bytes(b"frame-001")

    record = build_screenshot_provenance_from_image_path(
        image_path,
        parent_lineage_id="lineage_fr24batch_parent",
        metadata={"operator_note": "test"},
    )

    assert record.parent_lineage_id == "lineage_fr24batch_parent"
    assert record.metadata["operator_note"] == "test"
    assert record.metadata["filename"] == "fr24_web_frame_001.png"


def test_build_screenshot_provenance_missing_file_raises(tmp_path):
    with pytest.raises(ScreenshotProvenanceError, match="does not exist"):
        build_screenshot_provenance_from_image_path(tmp_path / "missing.jpeg")


def test_deterministic_batch_lineage_requires_hashes():
    with pytest.raises(ScreenshotProvenanceError, match="without image hashes"):
        deterministic_batch_lineage_id([])


def test_build_batch_screenshot_provenance_links_children_to_parent(tmp_path):
    second = tmp_path / "fr24_ios_frame_002.jpeg"
    first = tmp_path / "fr24_ios_frame_001.jpeg"
    second.write_bytes(b"second")
    first.write_bytes(b"first")

    batch = build_batch_screenshot_provenance(
        [second, first],
        batch_id="batch_test_001",
    )

    assert batch.batch_id == "batch_test_001"
    assert batch.batch_lineage_id.startswith("lineage_fr24batch_")
    assert len(batch.records) == 2
    assert [record.metadata["filename"] for record in batch.records] == [
        "fr24_ios_frame_001.jpeg",
        "fr24_ios_frame_002.jpeg",
    ]
    assert all(record.parent_lineage_id == batch.batch_lineage_id for record in batch.records)
    assert batch.child_lineage_ids == tuple(record.lineage_id for record in batch.records)

    payload = batch.to_dict()
    assert payload["batch_id"] == "batch_test_001"
    assert payload["batch_lineage_id"] == batch.batch_lineage_id
    assert payload["child_lineage_ids"] == list(batch.child_lineage_ids)
    assert len(payload["records"]) == 2


def test_build_batch_screenshot_provenance_empty_batch_raises():
    with pytest.raises(ScreenshotProvenanceError, match="at least one image"):
        build_batch_screenshot_provenance([])


def test_build_batch_screenshot_provenance_unsorted_when_requested(tmp_path):
    second = tmp_path / "fr24_ios_frame_002.jpeg"
    first = tmp_path / "fr24_ios_frame_001.jpeg"
    second.write_bytes(b"second")
    first.write_bytes(b"first")

    batch = build_batch_screenshot_provenance([second, first], sort_paths=False)

    assert [record.metadata["filename"] for record in batch.records] == [
        "fr24_ios_frame_002.jpeg",
        "fr24_ios_frame_001.jpeg",
    ]
