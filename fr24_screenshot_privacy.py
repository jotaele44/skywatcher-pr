"""FR24 screenshot privacy and redaction policy helpers.

This module defines metadata-level privacy controls for screenshot fixtures and
FR24 visual-analysis records. It does not perform image redaction; it enforces
policy decisions about whether raw screenshots may be committed or whether only
metadata/expected-output fixtures are allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


class ScreenshotPrivacyError(ValueError):
    """Raised when screenshot privacy metadata violates policy."""


class RedactionStatus(str, Enum):
    """Redaction state for a screenshot or fixture."""

    NOT_REVIEWED = "not_reviewed"
    REDACTION_NOT_REQUIRED = "redaction_not_required"
    REDACTION_REQUIRED = "redaction_required"
    REDACTED = "redacted"
    METADATA_ONLY = "metadata_only"
    REJECTED = "rejected"


class FixturePrivacyClass(str, Enum):
    """Allowed fixture storage classes for screenshot-derived tests."""

    SYNTHETIC = "synthetic"
    REDACTED_SCREENSHOT = "redacted_screenshot"
    METADATA_ONLY = "metadata_only"
    EXTERNAL_REFERENCE_ONLY = "external_reference_only"
    DO_NOT_COMMIT = "do_not_commit"


class SensitiveUIField(str, Enum):
    """Controlled list of sensitive screenshot/UI fields."""

    USER_ACCOUNT = "user_account"
    EMAIL_OR_HANDLE = "email_or_handle"
    DEVICE_STATUS_BAR = "device_status_bar"
    NOTIFICATION_BANNER = "notification_banner"
    CONTACT_OR_MESSAGE = "contact_or_message"
    PRECISE_PRIVATE_LOCATION = "precise_private_location"
    HOME_OR_SCHOOL_CONTEXT = "home_or_school_context"
    FACE_OR_PERSON = "face_or_person"
    VEHICLE_PLATE = "vehicle_plate"
    DEVICE_IDENTIFIER = "device_identifier"
    BROWSER_TAB_OR_HISTORY = "browser_tab_or_history"
    ACCESS_TOKEN_OR_SECRET = "access_token_or_secret"
    PAYMENT_OR_ACCOUNT_INFO = "payment_or_account_info"
    OTHER = "other"


RAW_COMMIT_ALLOWED_CLASSES = {
    FixturePrivacyClass.SYNTHETIC,
    FixturePrivacyClass.REDACTED_SCREENSHOT,
}
RAW_COMMIT_ALLOWED_STATUSES = {
    RedactionStatus.REDACTION_NOT_REQUIRED,
    RedactionStatus.REDACTED,
}
METADATA_ONLY_CLASSES = {
    FixturePrivacyClass.METADATA_ONLY,
    FixturePrivacyClass.EXTERNAL_REFERENCE_ONLY,
}


def normalize_sensitive_fields(
    fields: Iterable[SensitiveUIField | str] | None,
) -> tuple[SensitiveUIField, ...]:
    """Normalize and deduplicate sensitive UI field names."""

    if fields is None:
        return ()
    normalized: list[SensitiveUIField] = []
    for field in fields:
        try:
            normalized_field = field if isinstance(field, SensitiveUIField) else SensitiveUIField(field)
        except ValueError as exc:
            allowed = ", ".join(item.value for item in SensitiveUIField)
            raise ScreenshotPrivacyError(
                f"sensitive field must be one of: {allowed}; got {field!r}"
            ) from exc
        if normalized_field not in normalized:
            normalized.append(normalized_field)
    return tuple(normalized)


def classify_fixture_privacy(
    redaction_status: RedactionStatus | str,
    sensitive_fields: Sequence[SensitiveUIField | str] | None = None,
    *,
    is_synthetic: bool = False,
) -> FixturePrivacyClass:
    """Return the storage class required by redaction state and sensitive fields."""

    status = redaction_status if isinstance(redaction_status, RedactionStatus) else RedactionStatus(redaction_status)
    fields = normalize_sensitive_fields(sensitive_fields)

    if is_synthetic:
        return FixturePrivacyClass.SYNTHETIC
    if status == RedactionStatus.REDACTED:
        return FixturePrivacyClass.REDACTED_SCREENSHOT
    if status == RedactionStatus.REDACTION_NOT_REQUIRED and not fields:
        return FixturePrivacyClass.REDACTED_SCREENSHOT
    if status in {RedactionStatus.METADATA_ONLY, RedactionStatus.REDACTION_REQUIRED}:
        return FixturePrivacyClass.METADATA_ONLY
    if status in {RedactionStatus.REJECTED, RedactionStatus.NOT_REVIEWED}:
        return FixturePrivacyClass.DO_NOT_COMMIT
    if fields:
        return FixturePrivacyClass.METADATA_ONLY
    return FixturePrivacyClass.DO_NOT_COMMIT


@dataclass(frozen=True)
class ScreenshotPrivacyAssessment:
    """Privacy assessment for one screenshot or screenshot-derived fixture."""

    screenshot_id: str
    redaction_status: RedactionStatus
    sensitive_fields: Sequence[SensitiveUIField] = field(default_factory=tuple)
    fixture_privacy_class: FixturePrivacyClass | None = None
    policy_version: str = "1.0.0"
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        status = self.redaction_status
        if not isinstance(status, RedactionStatus):
            status = RedactionStatus(status)
            object.__setattr__(self, "redaction_status", status)

        fields = normalize_sensitive_fields(self.sensitive_fields)
        object.__setattr__(self, "sensitive_fields", fields)

        fixture_class = self.fixture_privacy_class
        if fixture_class is None:
            fixture_class = classify_fixture_privacy(status, fields)
        elif not isinstance(fixture_class, FixturePrivacyClass):
            fixture_class = FixturePrivacyClass(fixture_class)
        object.__setattr__(self, "fixture_privacy_class", fixture_class)
        self.validate()

    def validate(self) -> None:
        """Validate privacy-policy consistency."""

        if not self.screenshot_id or not isinstance(self.screenshot_id, str):
            raise ScreenshotPrivacyError("screenshot_id is required")
        if self.redaction_status == RedactionStatus.REDACTION_NOT_REQUIRED and self.sensitive_fields:
            raise ScreenshotPrivacyError(
                "redaction_not_required cannot include sensitive_fields"
            )
        if self.fixture_privacy_class in RAW_COMMIT_ALLOWED_CLASSES:
            if self.redaction_status not in RAW_COMMIT_ALLOWED_STATUSES:
                raise ScreenshotPrivacyError(
                    "raw fixture classes require redaction_not_required or redacted status"
                )
        if self.redaction_status == RedactionStatus.REDACTION_REQUIRED:
            if self.fixture_privacy_class not in {
                FixturePrivacyClass.METADATA_ONLY,
                FixturePrivacyClass.EXTERNAL_REFERENCE_ONLY,
                FixturePrivacyClass.DO_NOT_COMMIT,
            }:
                raise ScreenshotPrivacyError(
                    "redaction_required screenshots cannot be committed as raw fixtures"
                )

    @property
    def raw_image_commit_allowed(self) -> bool:
        """Whether the raw image file may be committed as a test fixture."""

        return (
            self.fixture_privacy_class in RAW_COMMIT_ALLOWED_CLASSES
            and self.redaction_status in RAW_COMMIT_ALLOWED_STATUSES
        )

    @property
    def metadata_only_required(self) -> bool:
        """Whether only metadata/expected-output fixtures may be committed."""

        return self.fixture_privacy_class in METADATA_ONLY_CLASSES

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible policy metadata."""

        return {
            "screenshot_id": self.screenshot_id,
            "redaction_status": self.redaction_status.value,
            "sensitive_fields": [field.value for field in self.sensitive_fields],
            "fixture_privacy_class": self.fixture_privacy_class.value,
            "raw_image_commit_allowed": self.raw_image_commit_allowed,
            "metadata_only_required": self.metadata_only_required,
            "policy_version": self.policy_version,
            "notes": self.notes,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ScreenshotPrivacyAssessment":
        """Create a privacy assessment from serialized metadata."""

        ignored = {"raw_image_commit_allowed", "metadata_only_required"}
        return cls(**{key: value for key, value in payload.items() if key not in ignored})
