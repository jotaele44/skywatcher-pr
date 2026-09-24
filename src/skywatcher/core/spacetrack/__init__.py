"""Space-Track.org acquisition and provenance control plane.

This package is deliberately read-only. Live credentials are injected by a
runtime transport outside the core package; no write/upload workflow is exposed.
Consumers should read frozen/local materializations rather than query
Space-Track directly.
"""

from .collector import CollectionResult, DownloadResult, SpaceTrackCollector
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
from .query import (
    SpaceTrackQuery,
    build_curated_favorites_query,
    build_incremental_query,
    build_publicfile_download_url,
)
from .storage import SpaceTrackStore
from .transport import ReadOnlyTransport, TransportResponse, UrlLibReadOnlyTransport

__all__ = [
    "CONTROLLER_CONTRACTS",
    "SOURCE_CONTRACTS",
    "CapabilityState",
    "CertificationState",
    "CollectionResult",
    "ControllerContract",
    "DistributionClass",
    "DownloadResult",
    "Manifestation",
    "ReadOnlyTransport",
    "SourceContract",
    "SpaceTrackCollector",
    "SpaceTrackControlPlane",
    "SpaceTrackQuery",
    "SpaceTrackStore",
    "TransportResponse",
    "UrlLibReadOnlyTransport",
    "Watermark",
    "build_curated_favorites_query",
    "build_incremental_query",
    "build_publicfile_download_url",
    "classify_archive_equivalence",
    "classify_decay_stage",
    "get_source_contract",
    "logical_json_sha256",
]
