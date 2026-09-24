"""Space-Track.org acquisition and provenance control plane.

This package is deliberately read-only.  Live credentials are injected by a
runtime transport outside the core package; no write/upload workflow is exposed.
Consumers should read frozen/local materializations rather than query
Space-Track directly.
"""

from .contracts import (
    CONTROLLER_CONTRACTS,
    SOURCE_CONTRACTS,
    ControllerContract,
    SourceContract,
    get_source_contract,
)
from .control_plane import (
    SpaceTrackControlPlane,
    classify_archive_equivalence,
    classify_decay_stage,
    logical_json_sha256,
)
from .models import (
    CapabilityState,
    CertificationState,
    DistributionClass,
    Manifestation,
    Watermark,
)
from .query import SpaceTrackQuery, build_incremental_query

__all__ = [
    "CONTROLLER_CONTRACTS",
    "SOURCE_CONTRACTS",
    "CapabilityState",
    "CertificationState",
    "ControllerContract",
    "DistributionClass",
    "Manifestation",
    "SourceContract",
    "SpaceTrackControlPlane",
    "SpaceTrackQuery",
    "Watermark",
    "build_incremental_query",
    "classify_archive_equivalence",
    "classify_decay_stage",
    "get_source_contract",
    "logical_json_sha256",
]
