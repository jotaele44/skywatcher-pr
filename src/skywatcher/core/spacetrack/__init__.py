"""Space-Track.org acquisition and provenance control plane.

This package is deliberately read-only. Live credentials are injected by a
runtime transport outside the core package; no write/upload workflow is exposed.
Consumers should read frozen/local materializations rather than query
Space-Track directly.
"""

from .certification import certify_local_runtime, certify_static_contracts
from .collector import CollectionResult, DownloadResult, SpaceTrackCollector
from .contradictions import ContradictionRegister
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
from .materialize import (
    materialize_space_objects,
    materialize_stored_space_objects,
    resolve_identity_bindings,
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
from .reentry import (
    build_reentry_assertions,
    materialize_reentry_events,
    materialize_stored_reentry_events,
)
from .storage import SpaceTrackStore
from .transport import ReadOnlyTransport, TransportResponse, UrlLibReadOnlyTransport

__all__ = [
    "CONTROLLER_CONTRACTS",
    "SOURCE_CONTRACTS",
    "CapabilityState",
    "CertificationState",
    "CollectionResult",
    "ContradictionRegister",
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
    "build_reentry_assertions",
    "certify_local_runtime",
    "certify_static_contracts",
    "classify_archive_equivalence",
    "classify_decay_stage",
    "get_source_contract",
    "logical_json_sha256",
    "materialize_reentry_events",
    "materialize_space_objects",
    "materialize_stored_reentry_events",
    "materialize_stored_space_objects",
    "resolve_identity_bindings",
]
