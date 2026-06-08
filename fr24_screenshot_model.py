"""Canonical FR24 screenshot model.

This module defines the stable record that every FR24 screenshot-derived
parameter must attach to. It is intentionally stdlib-only and compatible with the
repo's flat-module layout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping
import hashlib


class SourcePlatform(str, Enum):
    """Known screenshot source platforms."""

    FR24_IOS = "fr24_ios"
    FR24_ANDROID = "fr24_android"
    FR24_WEB = "fr24_web"
    FR24_UNKNOWN = "fr24_unknown"
    OTHER = "other"


class TemporalStatus(str, Enum):
    """Temporal precision state for a screenshot-derived observation."""

    EXACT = "exact"
    APPROXIMATE = "approximate"
    MISSING = "missing"
    INVALID = "invalid"


class GeometryStatus(str, Enum):
    """Spatial precision state for a screenshot-derived observation."""

    LOCATED = "located"
    APPROXIMATE = "approximate"
    UNLOCATED = "unlocated"
    INVALID = "invalid"


class CoordinateMethod(str, Enum):
    """How coordinates were recovered for the screenshot."""

    DIRECT_UI = "direct_ui"
    OCR = "ocr"
    GEOREFERENCED = "georeferenced"
    INFERRED = "inferred"
    MANUAL = "manual"
    MISSING = "missing"


class ReviewStatus(str, Enum):
    """Human/automation review state."""

    PENDING = "pending"
    AUTO_ACCEPTED = "auto_accepted"
    NEEDS_REVIEW = "needs_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PATCHED = "patched"


class EvidenceTier(str, Enum):
    """Evidence tier used by the wider intelligence workflow."""

    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"


class ScreenshotModelError(ValueError):
    """Raised when a screenshot record is internally inconsistent."""


def _coerce_enum(value: Any, enum_type: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise ScreenshotModelError(
            f"{field_name} must be one of: {allowed}; got {value!r}"
        ) from exc


def _validate_confidence(value: float | None, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
        raise ScreenshotModelError(f"{field_name} must be a number in [0, 1]")


def _normalize_datetime(value: datetime | str | None, field_name: str) -> str | None:
    """Return an ISO-8601 string or None.

    String values are accepted so OCR/manual extraction can preserve partial
    pipeline outputs, but they must parse as ISO datetimes if supplied.
    """

    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.isoformat()
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ScreenshotModelError(
                f"{field_name} must be ISO-8601 parseable; got {value!r}"
            ) from exc
        return value
    raise ScreenshotModelError(f"{field_name} must be datetime, str, or None")


def sha256_file(path: str | Path) -> str:
    """Return SHA-256 hex digest for a local screenshot file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deterministic_screenshot_id(image_sha256: str, source_platform: SourcePlatform | str) -> str:
    """Create a stable screenshot id from hash and platform."""

    platform = _coerce_enum(source_platform, SourcePlatform, "source_platform")
    digest_prefix = image_sha256[:16]
    return f"fr24shot_{platform.value}_{digest_prefix}"


def deterministic_lineage_id(screenshot_id: str) -> str:
    """Create a stable lineage id for screenshot-derived records."""

    return f"lineage_{screenshot_id}"


@dataclass(frozen=True)
class FR24ScreenshotRecord:
    """Canonical identity/provenance shell for one FR24 screenshot.

    This object is intentionally limited to identity, lineage, status, and coarse
    extraction fields. Detailed visual parameters belong in the later registry
    and sidecar layers.
    """

    screenshot_id: str
    image_path: str
    image_sha256: str
    source_platform: SourcePlatform = SourcePlatform.FR24_UNKNOWN
    capture_datetime_local: str | None = None
    capture_datetime_utc: str | None = None
    temporal_status: TemporalStatus = TemporalStatus.MISSING
    geometry_status: GeometryStatus = GeometryStatus.UNLOCATED
    coordinate_method: CoordinateMethod = CoordinateMethod.MISSING
    coordinate_confidence: float | None = None
    estimated_error_m: float | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING
    lineage_id: str | None = None
    evidence_tier: EvidenceTier = EvidenceTier.T2
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_platform",
            _coerce_enum(self.source_platform, SourcePlatform, "source_platform"),
        )
        object.__setattr__(
            self,
            "temporal_status",
            _coerce_enum(self.temporal_status, TemporalStatus, "temporal_status"),
        )
        object.__setattr__(
            self,
            "geometry_status",
            _coerce_enum(self.geometry_status, GeometryStatus, "geometry_status"),
        )
        object.__setattr__(
            self,
            "coordinate_method",
            _coerce_enum(self.coordinate_method, CoordinateMethod, "coordinate_method"),
        )
        object.__setattr__(
            self,
            "review_status",
            _coerce_enum(self.review_status, ReviewStatus, "review_status"),
        )
        object.__setattr__(
            self,
            "evidence_tier",
            _coerce_enum(self.evidence_tier, EvidenceTier, "evidence_tier"),
        )
        object.__setattr__(
            self,
            "capture_datetime_local",
            _normalize_datetime(self.capture_datetime_local, "capture_datetime_local"),
        )
        object.__setattr__(
            self,
            "capture_datetime_utc",
            _normalize_datetime(self.capture_datetime_utc, "capture_datetime_utc"),
        )
        if self.lineage_id is None:
            object.__setattr__(self, "lineage_id", deterministic_lineage_id(self.screenshot_id))
        self.validate()

    def validate(self) -> None:
        """Validate internal consistency."""

        if not self.screenshot_id or not isinstance(self.screenshot_id, str):
            raise ScreenshotModelError("screenshot_id is required")
        if not self.image_path or not isinstance(self.image_path, str):
            raise ScreenshotModelError("image_path is required")
        if not isinstance(self.image_sha256, str) or len(self.image_sha256) != 64:
            raise ScreenshotModelError("image_sha256 must be a 64-character hex string")
        try:
            int(self.image_sha256, 16)
        except ValueError as exc:
            raise ScreenshotModelError("image_sha256 must be hexadecimal") from exc
        _validate_confidence(self.coordinate_confidence, "coordinate_confidence")
        if self.estimated_error_m is not None and self.estimated_error_m < 0:
            raise ScreenshotModelError("estimated_error_m must be non-negative")
        if self.geometry_status == GeometryStatus.LOCATED and self.coordinate_method == CoordinateMethod.MISSING:
            raise ScreenshotModelError(
                "located geometry requires a non-missing coordinate_method"
            )
        if self.temporal_status == TemporalStatus.EXACT and self.capture_datetime_utc is None:
            raise ScreenshotModelError("exact temporal_status requires capture_datetime_utc")

    @property
    def is_ready_for_parameter_extraction(self) -> bool:
        """Whether this screenshot can move into parameter-family extraction."""

        return (
            self.temporal_status not in {TemporalStatus.INVALID}
            and self.geometry_status not in {GeometryStatus.INVALID}
            and self.review_status not in {ReviewStatus.REJECTED}
            and bool(self.lineage_id)
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""

        return {
            "screenshot_id": self.screenshot_id,
            "image_path": self.image_path,
            "image_sha256": self.image_sha256,
            "source_platform": self.source_platform.value,
            "capture_datetime_local": self.capture_datetime_local,
            "capture_datetime_utc": self.capture_datetime_utc,
            "temporal_status": self.temporal_status.value,
            "geometry_status": self.geometry_status.value,
            "coordinate_method": self.coordinate_method.value,
            "coordinate_confidence": self.coordinate_confidence,
            "estimated_error_m": self.estimated_error_m,
            "review_status": self.review_status.value,
            "lineage_id": self.lineage_id,
            "evidence_tier": self.evidence_tier.value,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FR24ScreenshotRecord":
        """Create a record from a mapping, applying enum validation."""

        return cls(**dict(payload))
