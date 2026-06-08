from datetime import datetime, timezone

import pytest

from fr24_screenshot_model import (
    CoordinateMethod,
    EvidenceTier,
    FR24ScreenshotRecord,
    GeometryStatus,
    ReviewStatus,
    ScreenshotModelError,
    SourcePlatform,
    TemporalStatus,
    deterministic_lineage_id,
    deterministic_screenshot_id,
    sha256_file,
)


VALID_SHA = "a" * 64


def test_screenshot_record_accepts_minimum_valid_payload():
    record = FR24ScreenshotRecord(
        screenshot_id="fr24shot_test_001",
        image_path="screenshots/example.jpeg",
        image_sha256=VALID_SHA,
    )

    assert record.screenshot_id == "fr24shot_test_001"
    assert record.source_platform == SourcePlatform.FR24_UNKNOWN
    assert record.temporal_status == TemporalStatus.MISSING
    assert record.geometry_status == GeometryStatus.UNLOCATED
    assert record.coordinate_method == CoordinateMethod.MISSING
    assert record.review_status == ReviewStatus.PENDING
    assert record.evidence_tier == EvidenceTier.T2
    assert record.lineage_id == deterministic_lineage_id("fr24shot_test_001")
    assert record.is_ready_for_parameter_extraction is True


def test_screenshot_record_serializes_to_json_compatible_dict():
    record = FR24ScreenshotRecord(
        screenshot_id="fr24shot_test_002",
        image_path="screenshots/example.jpeg",
        image_sha256=VALID_SHA,
        source_platform="fr24_ios",
        temporal_status="approximate",
        geometry_status="approximate",
        coordinate_method="manual",
        coordinate_confidence=0.6,
        estimated_error_m=120.0,
        review_status="needs_review",
        metadata={"note": "fixture"},
    )

    payload = record.to_dict()
    assert payload["source_platform"] == "fr24_ios"
    assert payload["temporal_status"] == "approximate"
    assert payload["geometry_status"] == "approximate"
    assert payload["coordinate_method"] == "manual"
    assert payload["review_status"] == "needs_review"
    assert payload["metadata"] == {"note": "fixture"}
    assert FR24ScreenshotRecord.from_dict(payload) == record


def test_exact_temporal_status_requires_utc_datetime():
    with pytest.raises(ScreenshotModelError, match="exact temporal_status"):
        FR24ScreenshotRecord(
            screenshot_id="fr24shot_test_003",
            image_path="screenshots/example.jpeg",
            image_sha256=VALID_SHA,
            temporal_status=TemporalStatus.EXACT,
        )


def test_iso_datetime_values_are_accepted_and_normalized():
    record = FR24ScreenshotRecord(
        screenshot_id="fr24shot_test_004",
        image_path="screenshots/example.jpeg",
        image_sha256=VALID_SHA,
        capture_datetime_local="2026-06-08T10:00:00-04:00",
        capture_datetime_utc=datetime(2026, 6, 8, 14, 0, tzinfo=timezone.utc),
        temporal_status="exact",
    )

    assert record.capture_datetime_local == "2026-06-08T10:00:00-04:00"
    assert record.capture_datetime_utc == "2026-06-08T14:00:00+00:00"


def test_invalid_datetime_string_is_rejected():
    with pytest.raises(ScreenshotModelError, match="ISO-8601"):
        FR24ScreenshotRecord(
            screenshot_id="fr24shot_test_005",
            image_path="screenshots/example.jpeg",
            image_sha256=VALID_SHA,
            capture_datetime_utc="not-a-date",
        )


def test_located_geometry_requires_coordinate_method():
    with pytest.raises(ScreenshotModelError, match="located geometry"):
        FR24ScreenshotRecord(
            screenshot_id="fr24shot_test_006",
            image_path="screenshots/example.jpeg",
            image_sha256=VALID_SHA,
            geometry_status=GeometryStatus.LOCATED,
            coordinate_method=CoordinateMethod.MISSING,
        )


def test_coordinate_confidence_must_be_between_zero_and_one():
    with pytest.raises(ScreenshotModelError, match="coordinate_confidence"):
        FR24ScreenshotRecord(
            screenshot_id="fr24shot_test_007",
            image_path="screenshots/example.jpeg",
            image_sha256=VALID_SHA,
            coordinate_confidence=1.5,
        )


def test_estimated_error_m_must_be_non_negative():
    with pytest.raises(ScreenshotModelError, match="estimated_error_m"):
        FR24ScreenshotRecord(
            screenshot_id="fr24shot_test_008",
            image_path="screenshots/example.jpeg",
            image_sha256=VALID_SHA,
            estimated_error_m=-1,
        )


def test_invalid_sha_is_rejected():
    with pytest.raises(ScreenshotModelError, match="64-character"):
        FR24ScreenshotRecord(
            screenshot_id="fr24shot_test_009",
            image_path="screenshots/example.jpeg",
            image_sha256="abc",
        )

    with pytest.raises(ScreenshotModelError, match="hexadecimal"):
        FR24ScreenshotRecord(
            screenshot_id="fr24shot_test_010",
            image_path="screenshots/example.jpeg",
            image_sha256="z" * 64,
        )


def test_invalid_enum_value_is_rejected():
    with pytest.raises(ScreenshotModelError, match="source_platform"):
        FR24ScreenshotRecord(
            screenshot_id="fr24shot_test_011",
            image_path="screenshots/example.jpeg",
            image_sha256=VALID_SHA,
            source_platform="bad_platform",
        )


def test_rejected_or_invalid_records_are_not_ready_for_parameter_extraction():
    rejected = FR24ScreenshotRecord(
        screenshot_id="fr24shot_test_012",
        image_path="screenshots/example.jpeg",
        image_sha256=VALID_SHA,
        review_status=ReviewStatus.REJECTED,
    )
    invalid_temporal = FR24ScreenshotRecord(
        screenshot_id="fr24shot_test_013",
        image_path="screenshots/example.jpeg",
        image_sha256=VALID_SHA,
        temporal_status=TemporalStatus.INVALID,
    )

    assert rejected.is_ready_for_parameter_extraction is False
    assert invalid_temporal.is_ready_for_parameter_extraction is False


def test_deterministic_ids_use_hash_and_platform():
    screenshot_id = deterministic_screenshot_id(VALID_SHA, SourcePlatform.FR24_IOS)
    assert screenshot_id == "fr24shot_fr24_ios_aaaaaaaaaaaaaaaa"
    assert deterministic_lineage_id(screenshot_id) == (
        "lineage_fr24shot_fr24_ios_aaaaaaaaaaaaaaaa"
    )


def test_sha256_file_hashes_local_file(tmp_path):
    image_path = tmp_path / "example.jpeg"
    image_path.write_bytes(b"fr24 screenshot bytes")

    assert sha256_file(image_path) == (
        "6f3244c600b4b9ca746da0c1e135a3e9224c3730db074f493fb4cf46194aa52f"
    )
