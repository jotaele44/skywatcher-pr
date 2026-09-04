"""Provenance-complete migration boundary for legacy infrastructure literals.

The manifest proves the exact code manifestation from which each assertion was
migrated.  It deliberately does not upgrade those literals into authoritative
real-world identity or geometry.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
from typing import Iterable

EXPECTED_HEAD = "6b95f816f1dc2c2081734df582920703743fbdf3"
EXPECTED_BLOB = "5650253d6641678e61a54044de282b6fdae3587e"
EXPECTED_COUNT = 24


class ManifestError(ValueError):
    pass


class AdmissionState(StrEnum):
    AUDIT_ONLY = "AUDIT_ONLY"
    BLOCKED = "BLOCKED"
    ADMITTED = "ADMITTED"


@dataclass(frozen=True)
class ManifestFeature:
    feature_id: str
    raw_name: str
    legacy_type: str
    latitude: float
    longitude: float
    radius_nm: float
    candidate_source_family: str
    migration_state: str
    identity_semantics: str
    certification_state: str
    production_admitted: bool


def _default_manifest_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data/infrastructure/legacy_infrastructure_source_manifest_v0_3.json"


def load_manifest(path: str | Path | None = None) -> dict:
    payload = json.loads(Path(path or _default_manifest_path()).read_text(encoding="utf-8"))
    validate_manifest(payload)
    return payload


def validate_manifest(payload: dict) -> None:
    if payload.get("schema_version") != "skywatcher.legacy-infrastructure-source-manifest.v0.3":
        raise ManifestError("unsupported schema_version")
    if payload.get("producer_source_head") != EXPECTED_HEAD:
        raise ManifestError("producer head drift")
    legacy = payload.get("legacy_source") or {}
    if legacy.get("git_blob_sha1") != EXPECTED_BLOB:
        raise ManifestError("legacy source blob drift")
    rows = payload.get("features") or []
    if len(rows) != EXPECTED_COUNT:
        raise ManifestError(f"feature denominator mismatch: {len(rows)} != {EXPECTED_COUNT}")
    ids = [str(row.get("feature_id") or "") for row in rows]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ManifestError("feature IDs must be nonempty and unique")
    defaults = payload.get("row_defaults") or {}
    if defaults.get("identity_semantics") != "CANDIDATE_NOT_IDENTITY":
        raise ManifestError("legacy rows must remain candidate-not-identity")
    if defaults.get("certification_state") != "AUDIT_ONLY":
        raise ManifestError("legacy rows must remain audit-only")
    if defaults.get("production_admitted") is not False:
        raise ManifestError("legacy rows may not be production-admitted")
    for row in rows:
        lat = float(row["latitude"])
        lon = float(row["longitude"])
        radius = float(row["radius_nm"])
        if not -90 <= lat <= 90 or not -180 <= lon <= 180 or radius < 0:
            raise ManifestError(f"invalid numeric geometry proxy for {row['feature_id']}")
        if not str(row.get("candidate_source_family") or "").strip():
            raise ManifestError(f"missing candidate source family for {row['feature_id']}")
    arithmetic = payload.get("arithmetic") or {}
    if arithmetic.get("legacy_literal_denominator") != len(rows):
        raise ManifestError("literal arithmetic does not close")
    if arithmetic.get("production_admitted") != 0 or arithmetic.get("audit_only") != len(rows):
        raise ManifestError("admission arithmetic does not close")


def iter_features(payload: dict) -> Iterable[ManifestFeature]:
    defaults = payload["row_defaults"]
    for row in payload["features"]:
        yield ManifestFeature(
            feature_id=row["feature_id"],
            raw_name=row["raw_name"],
            legacy_type=row["legacy_type"],
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            radius_nm=float(row["radius_nm"]),
            candidate_source_family=row["candidate_source_family"],
            migration_state=row["migration_state"],
            identity_semantics=defaults["identity_semantics"],
            certification_state=defaults["certification_state"],
            production_admitted=bool(defaults["production_admitted"]),
        )


def admission_state(payload: dict, *, production: bool) -> AdmissionState:
    validate_manifest(payload)
    if production:
        return AdmissionState.BLOCKED
    return AdmissionState.AUDIT_ONLY


def require_production_admission(payload: dict) -> None:
    state = admission_state(payload, production=True)
    if state is not AdmissionState.ADMITTED:
        raise ManifestError(
            "legacy hardcoded infrastructure is AUDIT_ONLY; authoritative source identity and geometry must be bound before production admission"
        )


def coordinate_collision_groups(payload: dict) -> dict[tuple[float, float], tuple[str, ...]]:
    groups: dict[tuple[float, float], list[str]] = {}
    for row in payload["features"]:
        key = (float(row["latitude"]), float(row["longitude"]))
        groups.setdefault(key, []).append(row["feature_id"])
    return {key: tuple(values) for key, values in groups.items() if len(values) > 1}
