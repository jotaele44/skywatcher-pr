"""Fail-closed consumer for Spiderweb spatial-analysis artifacts.

This module intentionally performs no geometry or raster calculation.  It
verifies producer authority, contract identity, hashes, null semantics and
candidate identity boundaries before exposing context to Skywatcher.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

CONTRACT_VERSION = "spatial-analysis-result/1.0"
PRODUCER_AUTHORITY = "spiderweb-pr"
SPATIAL_STATES = {"FULLY_WITHIN", "PARTIAL", "TOUCH_ONLY", "OUTSIDE", "NULL_EMPTY", "UNRESOLVED"}
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class SpatialArtifactError(ValueError):
    """Artifact failed a federation authority or integrity gate."""


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SpatialContext:
    analysis_id: str
    subject_id: str
    target_domain: str
    spatial_state: str
    identity_state: str
    target_feature_id: str | None
    target_candidate_id: str | None
    source_manifestation_ids: tuple[str, ...]
    measurement_classes: tuple[str, ...]
    result_hash: str
    artifact: Mapping[str, Any]


def consume_spiderweb_result(artifact: Mapping[str, Any]) -> SpatialContext:
    """Validate and consume one durable result without recomputing geometry."""
    if artifact.get("contract_version") != CONTRACT_VERSION:
        raise SpatialArtifactError("unsupported spatial-analysis contract")
    if artifact.get("producer_repo") != PRODUCER_AUTHORITY:
        raise SpatialArtifactError("geometry result is not Spiderweb-authoritative")
    supplied_hash = artifact.get("result_hash")
    if not isinstance(supplied_hash, str) or not _SHA256.fullmatch(supplied_hash):
        raise SpatialArtifactError("result_hash must be a lowercase SHA-256")
    payload = {k: v for k, v in artifact.items() if k != "result_hash"}
    if _canonical_hash(payload) != supplied_hash:
        raise SpatialArtifactError("result hash mismatch")
    state = artifact.get("spatial_state")
    if state not in SPATIAL_STATES:
        raise SpatialArtifactError("unknown spatial state")
    sources = artifact.get("source_manifestation_ids")
    measurements = artifact.get("measurement_classes")
    if not isinstance(sources, list) or not sources or len(sources) != len(set(sources)):
        raise SpatialArtifactError("source manifestations must be non-empty and unique")
    if not isinstance(measurements, list) or not measurements or len(measurements) != len(set(measurements)):
        raise SpatialArtifactError("measurement classes must be non-empty and unique")
    if artifact.get("target_candidate_id") is not None and artifact.get("identity_state") != "CANDIDATE_NOT_IDENTITY":
        raise SpatialArtifactError("candidate target was promoted to identity")
    quantitative = ("surface_depth_min_m", "surface_depth_max_m", "surface_depth_mean_m")
    if any(artifact.get(k) is not None for k in quantitative) and artifact.get("vertical_datum") is None:
        raise SpatialArtifactError("quantitative depth lacks vertical datum")
    if state == "NULL_EMPTY" and any(artifact.get(k) is not None for k in quantitative + ("distance_m", "intersection_length_m", "intersection_area_m2")):
        raise SpatialArtifactError("NULL_EMPTY contains synthesized measurements")
    return SpatialContext(
        analysis_id=str(artifact.get("analysis_id", "")), subject_id=str(artifact.get("subject_id", "")),
        target_domain=str(artifact.get("target_domain", "")), spatial_state=state,
        identity_state=str(artifact.get("identity_state", "")),
        target_feature_id=artifact.get("target_feature_id"), target_candidate_id=artifact.get("target_candidate_id"),
        source_manifestation_ids=tuple(sources), measurement_classes=tuple(measurements),
        result_hash=supplied_hash, artifact=dict(artifact),
    )


def consume_result_set(artifacts: Iterable[Mapping[str, Any]]) -> tuple[SpatialContext, ...]:
    """Consume whole records; reject duplicate analysis IDs or result hashes."""
    results = tuple(consume_spiderweb_result(item) for item in artifacts)
    ids = [item.analysis_id for item in results]
    hashes = [item.result_hash for item in results]
    if len(ids) != len(set(ids)):
        raise SpatialArtifactError("duplicate analysis_id in result set")
    if len(hashes) != len(set(hashes)):
        raise SpatialArtifactError("duplicate result_hash in result set")
    return results
