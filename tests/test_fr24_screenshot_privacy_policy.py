import pytest

from fr24_screenshot_privacy import (
    FixturePrivacyClass,
    RedactionStatus,
    ScreenshotPrivacyAssessment,
    ScreenshotPrivacyError,
    SensitiveUIField,
    classify_fixture_privacy,
    normalize_sensitive_fields,
)


def test_normalize_sensitive_fields_deduplicates_and_preserves_order():
    fields = normalize_sensitive_fields(
        [
            "device_status_bar",
            SensitiveUIField.USER_ACCOUNT,
            "device_status_bar",
        ]
    )

    assert fields == (
        SensitiveUIField.DEVICE_STATUS_BAR,
        SensitiveUIField.USER_ACCOUNT,
    )


def test_normalize_sensitive_fields_rejects_unknown_field():
    with pytest.raises(ScreenshotPrivacyError):
        normalize_sensitive_fields(["not_a_real_sensitive_field"])


def test_synthetic_fixture_class_overrides_status():
    assert (
        classify_fixture_privacy(
            RedactionStatus.NOT_REVIEWED,
            [SensitiveUIField.DEVICE_STATUS_BAR],
            is_synthetic=True,
        )
        == FixturePrivacyClass.SYNTHETIC
    )


def test_redaction_required_forces_metadata_only_fixture():
    assessment = ScreenshotPrivacyAssessment(
        screenshot_id="screenshot_001",
        redaction_status=RedactionStatus.REDACTION_REQUIRED,
        sensitive_fields=[SensitiveUIField.USER_ACCOUNT],
    )

    assert assessment.fixture_privacy_class == FixturePrivacyClass.METADATA_ONLY
    assert not assessment.raw_image_commit_allowed
    assert assessment.metadata_only_required


def test_redacted_screenshot_can_be_committed_as_raw_fixture():
    assessment = ScreenshotPrivacyAssessment(
        screenshot_id="screenshot_002",
        redaction_status=RedactionStatus.REDACTED,
        fixture_privacy_class=FixturePrivacyClass.REDACTED_SCREENSHOT,
    )

    assert assessment.raw_image_commit_allowed
    assert not assessment.metadata_only_required


def test_redaction_not_required_rejects_sensitive_fields():
    with pytest.raises(ScreenshotPrivacyError):
        ScreenshotPrivacyAssessment(
            screenshot_id="screenshot_003",
            redaction_status=RedactionStatus.REDACTION_NOT_REQUIRED,
            sensitive_fields=[SensitiveUIField.PRECISE_PRIVATE_LOCATION],
        )


def test_not_reviewed_is_do_not_commit():
    assessment = ScreenshotPrivacyAssessment(
        screenshot_id="screenshot_004",
        redaction_status=RedactionStatus.NOT_REVIEWED,
    )

    assert assessment.fixture_privacy_class == FixturePrivacyClass.DO_NOT_COMMIT
    assert not assessment.raw_image_commit_allowed
    assert not assessment.metadata_only_required


def test_serialization_round_trip_ignores_derived_flags():
    assessment = ScreenshotPrivacyAssessment(
        screenshot_id="screenshot_005",
        redaction_status=RedactionStatus.METADATA_ONLY,
        sensitive_fields=[SensitiveUIField.NOTIFICATION_BANNER],
        notes="FR24 screenshot contains notification overlay",
        metadata={"source": "manual_review"},
    )

    payload = assessment.to_dict()
    round_trip = ScreenshotPrivacyAssessment.from_dict(payload)

    assert round_trip == assessment
    assert payload["raw_image_commit_allowed"] is False
    assert payload["metadata_only_required"] is True


def test_raw_fixture_class_requires_safe_status():
    with pytest.raises(ScreenshotPrivacyError):
        ScreenshotPrivacyAssessment(
            screenshot_id="screenshot_006",
            redaction_status=RedactionStatus.REDACTION_REQUIRED,
            fixture_privacy_class=FixturePrivacyClass.REDACTED_SCREENSHOT,
            sensitive_fields=[SensitiveUIField.DEVICE_STATUS_BAR],
        )
