"""FR24 POI/icon reference registry validation and archive classification.

This module is intentionally stdlib-only. It owns the screenshot-reference
taxonomy contract, not physical-site identity. A source icon class is a
discovery/context signal and never promotes a POI, operator, or mission identity.
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = REPO / "configs" / "fr24_poi_icon_registry.json"

REQUIRED_RULES = (
    "preserve_raw_member_path",
    "raw_normalized_canonical_are_separate",
    "source_taxonomy_is_not_canonical_identity",
    "icon_similarity_is_discovery_only",
    "icon_match_does_not_prove_poi_identity",
    "poi_proximity_does_not_prove_aircraft_purpose",
    "composite_source_crop_may_emit_multiple_source_types",
    "unresolved_or_tied_match_requires_review",
    "road_and_avenue_markers_are_not_poi_identity",
    "operator_logo_match_is_candidate_not_identity",
    "unknown_is_not_absence",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _is_semantic_member(path: str) -> bool:
    name = Path(path).name
    return "__MACOSX" not in path and not name.startswith("._") and name != ".DS_Store"


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    """Load the registry without silently falling back to defaults."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("FR24 POI icon registry must be a JSON object")
    return data


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicate: set[str] = set()
    for value in values:
        if value in seen:
            duplicate.add(value)
        seen.add(value)
    return sorted(duplicate)


def validate_registry(data: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed structural/provenance validation for the V1 registry."""
    failures: list[str] = []
    warnings: list[str] = []

    if data.get("schema_version") != "fr24_poi_icon_registry/1.0":
        failures.append("unexpected schema_version")
    if data.get("registry_id") != "FR24_POI_ICON_REGISTRY_V1":
        failures.append("unexpected registry_id")

    rules = data.get("rules")
    if not isinstance(rules, dict):
        failures.append("rules must be an object")
        rules = {}
    for rule in REQUIRED_RULES:
        if rules.get(rule) is not True:
            failures.append(f"required rule missing or false: {rule}")

    feature_kinds = set(data.get("allowed_feature_kinds") or [])
    states = set(data.get("allowed_classification_states") or [])
    canonical = data.get("canonical_feature_types") or []
    source_types = data.get("source_icon_types") or []
    reserved = data.get("reserved_non_poi_icon_classes") or []
    manifestations = data.get("source_manifestations") or []
    archive_members = data.get("archive_members") or []
    source_archive = data.get("source_archive") or {}

    canonical_ids = [
        row.get("canonical_type_id") for row in canonical if isinstance(row, dict)
    ]
    source_ids = [
        row.get("source_type_id") for row in source_types if isinstance(row, dict)
    ]
    reserved_ids = [
        row.get("icon_class_id") for row in reserved if isinstance(row, dict)
    ]
    manifestation_ids = [
        row.get("manifestation_id") for row in manifestations if isinstance(row, dict)
    ]
    manifestation_paths = [
        row.get("raw_member_path") for row in manifestations if isinstance(row, dict)
    ]

    for label, values in (
        ("canonical_type_id", canonical_ids),
        ("source_type_id", source_ids),
        ("reserved icon_class_id", reserved_ids),
        ("manifestation_id", manifestation_ids),
        ("raw_member_path", manifestation_paths),
    ):
        if any(not isinstance(value, str) or not value for value in values):
            failures.append(f"{label} contains a missing/non-string value")
        dupes = _duplicates([value for value in values if isinstance(value, str)])
        if dupes:
            failures.append(f"duplicate {label}: {', '.join(dupes)}")

    canonical_set = {value for value in canonical_ids if isinstance(value, str)}
    source_set = {value for value in source_ids if isinstance(value, str)}
    reserved_set = {value for value in reserved_ids if isinstance(value, str)}
    manifestation_set = {
        value for value in manifestation_ids if isinstance(value, str)
    }
    if source_set & reserved_set:
        failures.append(
            "source_icon_types and reserved_non_poi_icon_classes overlap: "
            + ", ".join(sorted(source_set & reserved_set))
        )

    for row in canonical:
        if not isinstance(row, dict):
            failures.append("canonical_feature_types contains a non-object")
            continue
        cid = row.get("canonical_type_id")
        kind = row.get("feature_kind")
        if kind not in feature_kinds:
            failures.append(f"{cid}: unsupported feature_kind {kind!r}")
        if kind in {"TRANSPORT_FEATURE", "UNKNOWN"} and row.get("poi_eligible") is not False:
            failures.append(f"{cid}: {kind} must have poi_eligible=false")

    manifestation_by_id = {
        row["manifestation_id"]: row
        for row in manifestations
        if isinstance(row, dict) and isinstance(row.get("manifestation_id"), str)
    }
    for row in source_types:
        if not isinstance(row, dict):
            failures.append("source_icon_types contains a non-object")
            continue
        sid = row.get("source_type_id")
        if row.get("canonical_type_id") not in canonical_set:
            failures.append(f"{sid}: unknown canonical_type_id")
        if row.get("classification_state") not in states:
            failures.append(f"{sid}: unsupported classification_state")
        manifest_id = row.get("manifestation_id")
        if manifest_id not in manifestation_set:
            failures.append(f"{sid}: unknown manifestation_id {manifest_id!r}")
            continue
        manifest_refs = manifestation_by_id[manifest_id].get("source_type_ids") or []
        if sid not in manifest_refs:
            failures.append(f"{sid}: manifestation does not bind back to source type")

    archive_by_path: dict[str, dict[str, Any]] = {}
    archive_paths: list[str] = []
    for row in archive_members:
        if not isinstance(row, dict):
            failures.append("archive_members contains a non-object")
            continue
        path = row.get("path")
        sha = row.get("sha256")
        size = row.get("uncompressed_size")
        if not isinstance(path, str) or not path:
            failures.append("archive member missing path")
            continue
        archive_paths.append(path)
        if not isinstance(size, int) or size < 0:
            failures.append(f"{path}: invalid uncompressed_size")
        if not isinstance(sha, str) or not SHA256_RE.fullmatch(sha):
            failures.append(f"{path}: invalid sha256")
        archive_by_path[path] = row
    archive_dupes = _duplicates(archive_paths)
    if archive_dupes:
        failures.append("duplicate archive member paths: " + ", ".join(archive_dupes))

    full_manifest = sorted(archive_members, key=lambda row: row.get("path", ""))
    semantic_manifest = [
        row
        for row in full_manifest
        if isinstance(row, dict) and _is_semantic_member(str(row.get("path", "")))
    ]
    payload_multiset = sorted(
        [
            {
                "uncompressed_size": row.get("uncompressed_size"),
                "sha256": row.get("sha256"),
            }
            for row in archive_members
            if isinstance(row, dict)
        ],
        key=lambda row: (row["uncompressed_size"], row["sha256"]),
    )
    if _canonical_sha256(full_manifest) != source_archive.get("full_member_manifest_sha256"):
        failures.append("full archive member-manifest hash mismatch")
    if _canonical_sha256(semantic_manifest) != source_archive.get(
        "semantic_member_manifest_sha256"
    ):
        failures.append("semantic archive member-manifest hash mismatch")
    if _canonical_sha256(payload_multiset) != source_archive.get("payload_multiset_sha256"):
        failures.append("archive payload-multiset hash mismatch")

    count_expectations = {
        "full_non_directory_member_count": len(archive_members),
        "semantic_member_count": len(semantic_manifest),
        "metadata_member_count": len(archive_members) - len(semantic_manifest),
        "poi_source_member_count": sum(
            1
            for row in manifestations
            if isinstance(row, dict) and row.get("entity_kind") == "POI_ICON_SOURCE"
        ),
        "operator_logo_source_member_count": sum(
            1
            for row in manifestations
            if isinstance(row, dict) and row.get("entity_kind") == "OPERATOR_LOGO_SOURCE"
        ),
        "source_icon_type_count": len(source_types),
    }
    for key, actual in count_expectations.items():
        if source_archive.get(key) != actual:
            failures.append(
                f"{key}: declared {source_archive.get(key)!r}, computed {actual}"
            )

    for row in manifestations:
        if not isinstance(row, dict):
            failures.append("source_manifestations contains a non-object")
            continue
        manifest_id = row.get("manifestation_id")
        path = row.get("raw_member_path")
        member = archive_by_path.get(path)
        if member is None:
            failures.append(f"{manifest_id}: raw member not present in archive manifest")
            continue
        if row.get("uncompressed_size") != member.get("uncompressed_size"):
            failures.append(f"{manifest_id}: size does not match archive member")
        if row.get("sha256") != member.get("sha256"):
            failures.append(f"{manifest_id}: sha256 does not match archive member")
        refs = row.get("source_type_ids")
        if not isinstance(refs, list):
            failures.append(f"{manifest_id}: source_type_ids must be an array")
            continue
        invalid_refs = sorted(set(refs) - source_set)
        if invalid_refs:
            failures.append(
                f"{manifest_id}: unknown source_type_ids: {', '.join(invalid_refs)}"
            )
        kind = row.get("entity_kind")
        if kind == "POI_ICON_SOURCE":
            if not refs:
                failures.append(f"{manifest_id}: POI source has no source types")
            if row.get("identity_status") != "CANDIDATE_NOT_IDENTITY":
                failures.append(f"{manifest_id}: POI source must remain candidate-only")
            if row.get("composite_source_crop") != (len(refs) > 1):
                failures.append(f"{manifest_id}: composite_source_crop disagrees with refs")
        elif kind == "OPERATOR_LOGO_SOURCE":
            if refs:
                failures.append(f"{manifest_id}: operator-logo source cannot be a POI type")
            if row.get("identity_status") != "CANDIDATE_NOT_IDENTITY":
                failures.append(f"{manifest_id}: operator-logo match must remain candidate-only")
        else:
            failures.append(f"{manifest_id}: unsupported entity_kind {kind!r}")

    artwork_status = source_archive.get("source_artwork_redistribution_status")
    if artwork_status != "UNVERIFIED":
        warnings.append(
            "source artwork redistribution status changed from UNVERIFIED; "
            "confirm the repository pixel policy deliberately"
        )
    if source_archive.get("repository_pixel_policy") != (
        "DO_NOT_COMMIT_SOURCE_OR_DERIVED_THIRD_PARTY_ARTWORK_UNTIL_"
        "REDISTRIBUTION_RIGHTS_ARE_VERIFIED"
    ):
        failures.append("repository pixel policy missing or changed")

    return {
        "registry_id": data.get("registry_id"),
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "warnings": warnings,
        "counts": {
            "canonical_feature_types": len(canonical),
            "source_icon_types": len(source_types),
            "reserved_non_poi_icon_classes": len(reserved),
            "source_manifestations": len(manifestations),
            "archive_members": len(archive_members),
            "semantic_archive_members": len(semantic_manifest),
        },
    }


def validate_registry_file(path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    return validate_registry(load_registry(path))


def allowed_icon_class_ids(data: dict[str, Any]) -> list[str]:
    """Return the closed operator-label vocabulary, stable-sorted."""
    source = [
        row["source_type_id"]
        for row in data.get("source_icon_types", [])
        if isinstance(row, dict) and isinstance(row.get("source_type_id"), str)
    ]
    reserved = [
        row["icon_class_id"]
        for row in data.get("reserved_non_poi_icon_classes", [])
        if isinstance(row, dict) and isinstance(row.get("icon_class_id"), str)
    ]
    return sorted(set(source + reserved))


def resolve_icon_class(raw: str, data: dict[str, Any]) -> dict[str, Any]:
    """Resolve only explicit registry aliases; never infer identity from similarity."""
    needle = " ".join(str(raw).strip().casefold().split())
    candidates: set[str] = set()
    for row in data.get("source_icon_types", []):
        if not isinstance(row, dict):
            continue
        sid = row.get("source_type_id")
        labels = [
            sid,
            row.get("display_name", {}).get("en"),
            row.get("display_name", {}).get("es"),
            *(row.get("normalized_aliases") or []),
        ]
        if any(
            isinstance(label, str)
            and " ".join(label.strip().casefold().split()) == needle
            for label in labels
        ):
            candidates.add(str(sid))
    for row in data.get("reserved_non_poi_icon_classes", []):
        if not isinstance(row, dict):
            continue
        cid = row.get("icon_class_id")
        labels = [
            cid,
            row.get("display_name", {}).get("en"),
            row.get("display_name", {}).get("es"),
            *(row.get("legacy_aliases") or []),
        ]
        if any(
            isinstance(label, str)
            and " ".join(label.strip().casefold().split()) == needle
            for label in labels
        ):
            candidates.add(str(cid))
    ordered = sorted(candidates)
    if len(ordered) == 1:
        return {
            "resolution_status": "resolved",
            "icon_class_id": ordered[0],
            "candidates": ordered,
            "raw": raw,
        }
    if len(ordered) > 1:
        return {
            "resolution_status": "collision_review_required",
            "icon_class_id": None,
            "candidates": ordered,
            "raw": raw,
        }
    return {
        "resolution_status": "unresolved",
        "icon_class_id": None,
        "candidates": [],
        "raw": raw,
    }


def archive_member_manifest(zip_path: Path) -> list[dict[str, Any]]:
    """Hash every non-directory member, including metadata/resource forks."""
    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            payload = archive.read(info.filename)
            rows.append(
                {
                    "path": info.filename,
                    "uncompressed_size": info.file_size,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
    return sorted(rows, key=lambda row: row["path"])


def verify_source_archive(
    zip_path: Path, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Classify archive equivalence without conflating byte and payload identity."""
    if data is None:
        data = load_registry()
    expected = data["source_archive"]
    raw = zip_path.read_bytes()
    outer_sha = hashlib.sha256(raw).hexdigest()
    try:
        members = archive_member_manifest(zip_path)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        return {
            "status": "UNRESOLVED",
            "archive_sha256": outer_sha,
            "error": f"{type(exc).__name__}: {exc}",
            "install_allowed": False,
        }

    full_hash = _canonical_sha256(members)
    payload_multiset = sorted(
        [
            {
                "uncompressed_size": row["uncompressed_size"],
                "sha256": row["sha256"],
            }
            for row in members
        ],
        key=lambda row: (row["uncompressed_size"], row["sha256"]),
    )
    payload_hash = _canonical_sha256(payload_multiset)
    if outer_sha == expected["sha256"]:
        equivalence = "BYTE_IDENTICAL"
    elif full_hash == expected["full_member_manifest_sha256"]:
        equivalence = "PURE_RECOMPRESSION"
    elif payload_hash == expected["payload_multiset_sha256"]:
        equivalence = "SAME_PAYLOADS_DIFFERENT_PATHS"
    else:
        equivalence = "DISTINCT_PAYLOADS"

    return {
        "status": equivalence,
        "archive_sha256": outer_sha,
        "full_member_manifest_sha256": full_hash,
        "payload_multiset_sha256": payload_hash,
        "member_count": len(members),
        "install_allowed": equivalence in {"BYTE_IDENTICAL", "PURE_RECOMPRESSION"},
    }
