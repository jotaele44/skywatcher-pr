"""Core contracts for Skywatcher certified imagery acquisition.

Transport/provenance semantics intentionally mirror spiderweb-pr's source-adapter
SDK. Domain promotion semantics remain Skywatcher-specific.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence


class SourceAdapterError(RuntimeError):
    pass


ALLOWED_RIGHTS = {"ALLOWED", "PROHIBITED", "UNKNOWN"}
ALLOWED_REVIEW = {"dry_run", "cache_hit", "raw", "hold", "failed", "validated", "promoted", "unchanged", "changed"}


@dataclass(frozen=True)
class AcquisitionRights:
    fetch: str = "UNKNOWN"
    training: str = "UNKNOWN"
    redistribution: str = "UNKNOWN"

    def validate(self) -> None:
        values = {self.fetch, self.training, self.redistribution}
        bad = values - ALLOWED_RIGHTS
        if bad:
            raise SourceAdapterError(f"invalid rights state(s): {sorted(bad)}")


@dataclass(frozen=True)
class ImagerySourceEndpoint:
    source_id: str
    name: str
    url: str
    method: str = "GET"
    authority: str = ""
    source_lineage_id: str = ""
    imagery_provider: str = ""
    product_id: str = ""
    imagery_epoch: str = "UNKNOWN"
    rights: AcquisitionRights = field(default_factory=AcquisitionRights)
    notes: str = ""

    def validate(self) -> None:
        self.rights.validate()
        if not self.source_id or not self.url or not self.source_lineage_id:
            raise SourceAdapterError("source_id, url, and source_lineage_id are required")


@dataclass(frozen=True)
class AdapterPolicy:
    raw_payload_root: Path
    manifest_root: Path
    staging_root: Path
    cache_root: Path
    promoted_output_root: Path | None = None
    allow_raw_commit: bool = False
    allow_extracted_commit: bool = False

    def validate_runtime_paths(self) -> None:
        if self.allow_raw_commit or self.allow_extracted_commit:
            raise SourceAdapterError("raw/extracted payload commits are prohibited")
        for path in (self.raw_payload_root, self.manifest_root, self.staging_root, self.cache_root):
            if not isinstance(path, Path):
                raise SourceAdapterError("adapter paths must be pathlib.Path instances")


@dataclass(frozen=True)
class PayloadRequest:
    request_id: str
    endpoint: ImagerySourceEndpoint
    params: Mapping[str, str] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    expected_content: str = ""
    expected_sha256: str = ""
    filename_hint: str = ""

    def validate(self) -> None:
        self.endpoint.validate()
        if not self.request_id:
            raise SourceAdapterError("request_id is required")
        if self.endpoint.rights.fetch == "PROHIBITED":
            raise SourceAdapterError("fetch prohibited by source rights state")


@dataclass(frozen=True)
class CertifiedFetchResult:
    request_id: str
    source_id: str
    source_lineage_id: str
    source_url: str
    final_url: str
    request_method: str
    request_params: str
    retrieval_utc: str
    http_status: int | str
    content_type: str
    etag: str
    last_modified: str
    filename: str
    sha256: str
    bytes: int
    review_status: str
    previous_sha256: str = ""
    change_state: str = "UNKNOWN"
    error: str = ""

    def validate(self) -> None:
        if self.review_status not in ALLOWED_REVIEW:
            raise SourceAdapterError(f"invalid review_status: {self.review_status}")
        if self.sha256 and (len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256.lower())):
            raise SourceAdapterError("sha256 must be a 64-character hex digest")


@dataclass(frozen=True)
class CoverageSummary:
    expected: int
    requested: int
    acquired: int
    failed: int
    hold: int
    cache_hit: int = 0
    unresolved: int = 0

    @property
    def coverage_pct(self) -> float:
        denominator = self.requested or self.expected
        return 0.0 if denominator <= 0 else round((self.acquired / denominator) * 100, 2)


def require_training_eligible(endpoint: ImagerySourceEndpoint) -> None:
    """Block calibration promotion unless training rights are affirmative."""
    endpoint.validate()
    if endpoint.rights.training != "ALLOWED":
        raise SourceAdapterError("training eligibility is not affirmatively ALLOWED")


def require_redistribution_eligible(endpoint: ImagerySourceEndpoint) -> None:
    endpoint.validate()
    if endpoint.rights.redistribution != "ALLOWED":
        raise SourceAdapterError("redistribution eligibility is not affirmatively ALLOWED")
