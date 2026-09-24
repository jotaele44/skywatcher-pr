"""Typed records for the Space-Track control plane."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CertificationState(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"
    PROVISIONAL = "PROVISIONAL"
    AUDIT_ONLY = "AUDIT_ONLY"
    NONCANONICAL = "NONCANONICAL"
    CANDIDATE_NOT_IDENTITY = "CANDIDATE_NOT_IDENTITY"
    UNRESOLVED = "UNRESOLVED"
    SUPERSEDED = "SUPERSEDED"


class CapabilityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    AUTHORIZED_EMPTY = "AUTHORIZED_EMPTY"
    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNVERIFIED = "UNVERIFIED"


class DistributionClass(str, Enum):
    BASIC_SSA_CITABLE = "BASIC_SSA_CITABLE"
    PUBLIC_FILE = "PUBLIC_FILE"
    ACCOUNT_ONLY = "ACCOUNT_ONLY"
    ODR_CONTROLLED = "ODR_CONTROLLED"
    SSA_AGREEMENT_CONTROLLED = "SSA_AGREEMENT_CONTROLLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Watermark:
    source_id: str
    predicate: str
    value: str
    contract_version: str = "spacetrack.v1"


@dataclass(frozen=True)
class Manifestation:
    source_id: str
    controller: str
    query: str
    retrieved_utc: str
    raw_sha256: str
    byte_count: int
    row_count: int | None
    schema_sha256: str | None
    distribution_class: DistributionClass
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceArithmetic:
    source_count: int
    retained_count: int
    excluded_count: int

    @property
    def closes(self) -> bool:
        return self.source_count == self.retained_count + self.excluded_count


@dataclass(frozen=True)
class ArchiveMember:
    path: str
    uncompressed_size: int
    sha256: str


@dataclass(frozen=True)
class ArchiveSnapshot:
    outer_sha256: str
    members: tuple[ArchiveMember, ...]


@dataclass(frozen=True)
class SchemaSnapshot:
    source_id: str
    retrieved_utc: str
    canonical_sha256: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class CapabilityObservation:
    controller: str
    state: CapabilityState
    observed_utc: str
    detail: str | None = None


@dataclass(frozen=True)
class NormalizedBatch:
    source_id: str
    retrieved_utc: str
    query: str
    raw_sha256: str
    schema_sha256: str | None
    rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ContradictionRecord:
    contradiction_id: str
    category: str
    key: str
    observations: tuple[str, ...]
    state: CertificationState = CertificationState.UNRESOLVED


@dataclass(frozen=True)
class IdentityBinding:
    catalog_key: str
    norad_cat_id: str | None
    object_id: str | None
    state: CertificationState
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class SpaceObjectView:
    catalog_key: str
    norad_cat_id: str
    object_id: str | None
    identity_state: CertificationState
    satcat_row: dict[str, Any] | None
    gp_row: dict[str, Any] | None
    aliases: tuple[str, ...]
    contradictions: tuple[str, ...]


@dataclass(frozen=True)
class MaterializationResult:
    satcat_row_count: int
    gp_row_count: int
    object_count: int
    unmatched_satcat: tuple[str, ...]
    unmatched_gp: tuple[str, ...]
    contradictions: tuple[ContradictionRecord, ...]
    objects: tuple[SpaceObjectView, ...]
