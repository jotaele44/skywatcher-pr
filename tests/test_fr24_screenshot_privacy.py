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


def test_normalize_sensitive_fields_deduplicates_and_coerces_strings():
    fields = normalize_sensitive_fields(
        [
            "device_status_bar",
            SensitiveUIField.DEVICE_STATUS_BAR,
            "notification_banner",
        ]
    )

    assert fields == (
        SensitiveUIField.DEVICE_STATUS_BAR,
        SensitiveUIField.NOTIFICATION_BANNER,
    )


def test_invalid_sensitive_field_is_rejected():
    with pytest.raises(ScreenshotPrivacyError, match="sensitive field"):
        normalize_sensitive_fields(["not_a_real_field"])


def test_classify_fixture_privacy_allows_synthetic_when_requested():
    assert classify_fixture_privacy(
        RedactionStatus.REDACTION_NOT_REQUIRED,
        is_synthetic=True,
    ) == FixturePrivacyClass.SYNTHETIC


def test_classify_fixture_privacy_requires_metadata_only_for_sensitive_or_pending_redaction():
    assert classify_fixture_privacy(
        RedactionStatus.REDACTION_REQUIRED,
        [SensitiveUIField.DEVICE_STATUS_BAR],
    ) == FixturePrivacyClass.METADATA_ONLY

    assert classify_fixture_privacy(
        RedactionStatus.METADATA_ONLY,
    ) == FixturePrivacyClass.METADATA_ONLY


def test_classify_fixture_privacy_rejects_unreviewed_or_rejected():
    assert classify_fixture_privacy(
        RedactionStatus.NOT_REVIEWED,
    ) == FixturePrivacyClass.DO_NOT_COMMIT
    assert classify_fixture_privacy(
        RedactionStatus.REJECTED,
    ) == FixturePrivacyClass.DO_NOT_COMMIT


def test_privacy_assessment_serializes_policy_flags():
    assessment = ScreenshotPrivacyAssessment(
        screenshot_id="fr24shot_test_001",
        redaction_status=RedactionStatus.REDACTED,
        sensitive_fields=["device_status_bar", "notification_banner"],
        notes="status bar removed",
        metadata={"fixture_group": "ui_overlay_heavy"},
    )

    payload = assessment.to_dict()
    assert payload["screenshot_id"] == "fr24shot_test_001"
    assert payload["redaction_status"] == "redacted"
    assert payload["fixture_privacy_class"] == "redacted_screenshot"
    assert payload["raw_image_commit_allowed"] is True
    assert payload["metadata_only_required"] is False
    assert payload["sensitive_fields"] == [
        "device_status_bar",
        "notification_banner",
    ]
    assert ScreenshotPrivacyAssessment.from_dict(payload) == assessment


def test_metadata_only_assessment_blocks_raw_image_commit():
    assessment = ScreenshotPrivacyAssessment(
        screenshot_id="fr24shot_test_002",
        redaction_status="redaction_required",
        sensitive_fields=["email_or_handle"],
    )

    assert assessment.fixture_privacy_class == FixturePrivacyClass.METADATA_ONLY
    assert assessment.raw_image_commit_allowed is False
    assert assessment.metadata_only_required is True


def test_redaction_not_required_cannot_have_sensitive_fields():
    with pytest.raises(ScreenshotPrivacyError, match="cannot include sensitive_fields"):
        ScreenshotPrivacyAssessment(
            screenshot_id="fr24shot_test_003",
            redaction_status=RedactionStatus.REDACTION_NOT_REQUIRED,
            sensitive_fields=[SensitiveUIField.FACE_OR_PERSON],
        )


def test_raw_fixture_class_requires_clean_or_redacted_status():
    with pytest.raises(ScreenshotPrivacyError, match="raw fixture classes"):
        ScreenshotPrivacyAssessment(
            screenshot_id="fr24shot_test_004",
            redaction_status=RedactionStatus.NOT_REVIEWED,
            fixture_privacy_class=FixturePrivacyClass.REDACTED_SCREENSHOT,
        )


def test_redaction_required_cannot_be_raw_fixture():
    with pytest.raises(ScreenshotPrivacyError, match="cannot be committed as raw"):
        ScreenshotPrivacyAssessment(
            screenshot_id="fr24shot_test_005",
            redaction_status=RedactionStatus.REDACTION_REQUIRED,
            sensitive_fields=[SensitiveUIField.DEVICE_STATUS_BAR],
            fixture_privacy_class=FixturePrivacyClass.REDACTED_SCREENSHOT,
        )


def test_screenshot_id_is_required():
    with pytest.raises(ScreenshotPrivacyError, match="screenshot_id"):
        ScreenshotPrivacyAssessment(
            screenshot_id="",
            redaction_status=RedactionStatus.REDACTED,
        )
