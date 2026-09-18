"""Skywatcher certified acquisition SDK.

Mirrors the transport/provenance contract used by spiderweb-pr source adapters
while adding imagery-calibration rights, lineage, and promotion gates.
"""

from .core import (
    AcquisitionRights,
    AdapterPolicy,
    CertifiedFetchResult,
    ImagerySourceEndpoint,
    PayloadRequest,
    SourceAdapterError,
)
from .download import CertifiedFetchEngine, PayloadValidator
from .manifest import ManifestEngine, summarize_coverage

__all__ = [
    "AcquisitionRights",
    "AdapterPolicy",
    "CertifiedFetchEngine",
    "CertifiedFetchResult",
    "ImagerySourceEndpoint",
    "ManifestEngine",
    "PayloadRequest",
    "PayloadValidator",
    "SourceAdapterError",
    "summarize_coverage",
]
