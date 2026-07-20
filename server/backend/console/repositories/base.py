"""Common repository result and provenance-accounting primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VALID_AVAILABILITY_STATUSES = {
    "available",
    "available_synthetic_only",
    "unavailable_no_artifact",
    "unavailable_no_adapter",
    "disabled_by_policy",
    "degraded",
}

REQUIRED_PROVENANCE_KEYS = {
    "source_family",
    "source_provider",
    "source_method",
    "data_rights",
    "operational_mode",
    "source_record_id",
    "lineage_id",
    "artifact_path",
    "ingest_adapter",
}


@dataclass(frozen=True)
class ArtifactRef:
    path: str
    kind: str
    exists: bool
    size_bytes: int | None = None
    sha256: str | None = None
    configured_by: str | None = None
    record_count: int | None = None
    status: str = "candidate"
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "configured_by": self.configured_by,
            "record_count": self.record_count,
            "status": self.status,
            "error": self.error,
        }


def row_has_complete_provenance(row: dict[str, Any]) -> bool:
    provenance = row.get("provenance")
    if not isinstance(provenance, dict):
        return False
    return all(provenance.get(key) not in (None, "") for key in REQUIRED_PROVENANCE_KEYS)


@dataclass
class RepositorySnapshot:
    repository: str
    status: str
    reason: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[ArtifactRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_rows: int = 0

    def __post_init__(self) -> None:
        if self.status not in VALID_AVAILABILITY_STATUSES:
            raise ValueError(f"unsupported repository status: {self.status}")

    @property
    def record_count(self) -> int:
        return len(self.rows)

    @property
    def synthetic_only(self) -> bool:
        return bool(self.rows) and all(bool(row.get("synthetic")) for row in self.rows)

    @property
    def provenance_complete(self) -> bool:
        return all(row_has_complete_provenance(row) for row in self.rows)

    @property
    def source_methods(self) -> list[str]:
        return sorted(
            {
                str(row.get("provenance", {}).get("source_method"))
                for row in self.rows
                if row.get("provenance", {}).get("source_method")
            }
        )

    @property
    def source_families(self) -> list[str]:
        return sorted(
            {
                str(row.get("provenance", {}).get("source_family"))
                for row in self.rows
                if row.get("provenance", {}).get("source_family")
            }
        )

    def as_status(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "status": self.status,
            "reason": self.reason,
            "record_count": self.record_count,
            "synthetic_only": self.synthetic_only,
            "provenance_complete": self.provenance_complete,
            "source_methods": self.source_methods,
            "source_families": self.source_families,
            "skipped_rows": self.skipped_rows,
            "warnings": list(self.warnings),
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
        }


def finalize_snapshot(
    repository: str,
    rows: list[dict[str, Any]],
    artifacts: list[ArtifactRef],
    *,
    absent_reason: str,
    empty_reason: str | None = None,
    warnings: list[str] | None = None,
    skipped_rows: int = 0,
) -> RepositorySnapshot:
    warnings = list(warnings or [])
    existing = [artifact for artifact in artifacts if artifact.exists]
    errors = [artifact for artifact in artifacts if artifact.error]

    if rows:
        if all(bool(row.get("synthetic")) for row in rows):
            status = "available_synthetic_only"
            reason = "Only explicitly synthetic test records are available."
        elif errors or skipped_rows:
            status = "degraded"
            reason = "Records are available, but one or more artifacts or rows were rejected."
        else:
            status = "available"
            reason = "One or more bounded artifacts were loaded successfully."
    elif existing and errors:
        status = "degraded"
        reason = "Candidate artifacts exist but could not be loaded safely."
    elif existing:
        status = "unavailable_no_artifact"
        reason = empty_reason or "Candidate artifacts exist but contain no eligible records."
    else:
        status = "unavailable_no_artifact"
        reason = absent_reason

    snapshot = RepositorySnapshot(
        repository=repository,
        status=status,
        reason=reason,
        rows=rows,
        artifacts=artifacts,
        warnings=warnings,
        skipped_rows=skipped_rows,
    )
    if rows and not snapshot.provenance_complete:
        snapshot.status = "degraded"
        snapshot.reason = "Rows were loaded, but row-level provenance is incomplete."
        snapshot.warnings.append("row_level_provenance_incomplete")
    return snapshot
