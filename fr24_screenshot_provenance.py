"""FR24 screenshot provenance builders.

Factories that turn local screenshot files into canonical FR24ScreenshotRecord
objects with stable hashes, IDs, source platform inference, and batch lineage.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import hashlib

from fr24_screenshot_model import (
    CoordinateMethod,
    EvidenceTier,
    FR24ScreenshotRecord,
    GeometryStatus,
    ReviewStatus,
    SourcePlatform,
    TemporalStatus,
    deterministic_screenshot_id,
    sha256_file,
)


class ScreenshotProvenanceError(ValueError):
    """Raised when screenshot provenance cannot be built."""


SOURCE_PLATFORM_KEYWORDS = {
    SourcePlatform.FR24_IOS: ("fr24_ios", "ios", "iphone", "ipad"),
    SourcePlatform.FR24_ANDROID: ("fr24_android", "android"),
    SourcePlatform.FR24_WEB: (
        "fr24_web",
        "web",
        "browser",
        "chrome",
        "desktop",
        "safari",
    ),
}


def infer_source_platform(
    path: str | Path,
    explicit: SourcePlatform | str | None = None,
) -> SourcePlatform:
    """Infer FR24 screenshot platform from path/name, unless explicit is supplied."""

    if explicit is not None:
        return SourcePlatform(explicit)

    lowered = str(path).lower()
    if "fr24" not in lowered and "flightradar" not in lowered:
        return SourcePlatform.OTHER

    for platform, keywords in SOURCE_PLATFORM_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return platform

    return SourcePlatform.FR24_UNKNOWN


def deterministic_batch_lineage_id(
    image_hashes: Sequence[str],
    batch_id: str | None = None,
) -> str:
    """Create a stable parent lineage id for a screenshot batch."""

    if not image_hashes:
        raise ScreenshotProvenanceError("cannot create batch lineage without image hashes")
    seed = batch_id or "|".join(sorted(image_hashes))
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"lineage_fr24batch_{digest}"


@dataclass(frozen=True)
class FR24ScreenshotBatchProvenance:
    """Parent object for a batch of screenshot provenance records."""

    batch_id: str
    batch_lineage_id: str
    records: tuple[FR24ScreenshotRecord, ...]

    @property
    def child_lineage_ids(self) -> tuple[str, ...]:
        """Lineage ids of screenshot records in this batch."""

        return tuple(record.lineage_id for record in self.records if record.lineage_id)

    def to_dict(self) -> dict[str, Any]:
        """Serialize batch provenance to JSON-compatible structure."""

        return {
            "batch_id": self.batch_id,
            "batch_lineage_id": self.batch_lineage_id,
            "child_lineage_ids": list(self.child_lineage_ids),
            "records": [record.to_dict() for record in self.records],
        }


def build_screenshot_provenance_from_image_path(
    image_path: str | Path,
    *,
    source_platform: SourcePlatform | str | None = None,
    parent_lineage_id: str | None = None,
    capture_datetime_local: str | None = None,
    capture_datetime_utc: str | None = None,
    temporal_status: TemporalStatus | str = TemporalStatus.MISSING,
    geometry_status: GeometryStatus | str = GeometryStatus.UNLOCATED,
    coordinate_method: CoordinateMethod | str = CoordinateMethod.MISSING,
    coordinate_confidence: float | None = None,
    estimated_error_m: float | None = None,
    review_status: ReviewStatus | str = ReviewStatus.PENDING,
    evidence_tier: EvidenceTier | str = EvidenceTier.T2,
    metadata: Mapping[str, Any] | None = None,
) -> FR24ScreenshotRecord:
    """Build canonical screenshot provenance from a local image path."""

    path = Path(image_path)
    if not path.exists() or not path.is_file():
        raise ScreenshotProvenanceError(f"screenshot file does not exist: {path}")

    image_sha256 = sha256_file(path)
    platform = infer_source_platform(path, source_platform)
    screenshot_id = deterministic_screenshot_id(image_sha256, platform)
    record_metadata = dict(metadata or {})
    record_metadata.setdefault("filename", path.name)
    record_metadata.setdefault("file_size_bytes", path.stat().st_size)

    return FR24ScreenshotRecord(
        screenshot_id=screenshot_id,
        image_path=str(path),
        image_sha256=image_sha256,
        source_platform=platform,
        capture_datetime_local=capture_datetime_local,
        capture_datetime_utc=capture_datetime_utc,
        temporal_status=temporal_status,
        geometry_status=geometry_status,
        coordinate_method=coordinate_method,
        coordinate_confidence=coordinate_confidence,
        estimated_error_m=estimated_error_m,
        review_status=review_status,
        parent_lineage_id=parent_lineage_id,
        evidence_tier=evidence_tier,
        metadata=record_metadata,
    )


def build_batch_screenshot_provenance(
    image_paths: Iterable[str | Path],
    *,
    batch_id: str | None = None,
    source_platform: SourcePlatform | str | None = None,
    sort_paths: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> FR24ScreenshotBatchProvenance:
    """Build provenance records for a screenshot batch with shared parent lineage."""

    paths = [Path(path) for path in image_paths]
    if sort_paths:
        paths = sorted(paths, key=lambda path: str(path))
    if not paths:
        raise ScreenshotProvenanceError("batch provenance requires at least one image path")

    hashes = [sha256_file(path) for path in paths]
    batch_lineage_id = deterministic_batch_lineage_id(hashes, batch_id)
    resolved_batch_id = batch_id or batch_lineage_id.replace("lineage_", "")
    records = tuple(
        build_screenshot_provenance_from_image_path(
            path,
            source_platform=source_platform,
            parent_lineage_id=batch_lineage_id,
            metadata={**dict(metadata or {}), "batch_id": resolved_batch_id},
        )
        for path in paths
    )

    return FR24ScreenshotBatchProvenance(
        batch_id=resolved_batch_id,
        batch_lineage_id=batch_lineage_id,
        records=records,
    )
