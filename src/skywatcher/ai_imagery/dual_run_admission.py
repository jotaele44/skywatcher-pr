"""Offline S06 package admission for ADR 0006 S07."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from ._dual_run_common import (
    DualRunProjectionError,
    canonical_json_bytes,
    ensure_revision,
    ensure_sha256,
    ensure_trial_id,
    require_mapping,
    sha256_bytes,
    sha256_json,
    validate_campaign,
)
from .dual_run_projection import (
    S05_FILE_MAP,
    _validate_policy,
    _validate_receipt,
    _verify_s05_package,
    build_candidate_lane_projection_input,
    build_legacy_lane_projection_input,
)
from .legacy_shadow_export import canonical_legacy_shadow_export_bytes


class DualRunAdmissionError(DualRunProjectionError):
    """S07 admission failed closed."""


class ReceiptVerificationResolver(Protocol):
    """Resolve one injected H09 verification record."""

    def resolve(self, full_receipt: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return the verified binding for ``full_receipt``."""
        raise NotImplementedError


def _fail(message: str) -> DualRunAdmissionError:
    return DualRunAdmissionError(message)


def _projection_failure(exc: DualRunProjectionError) -> DualRunAdmissionError:
    message = str(exc).replace("normalized package digest", "normalized digest")
    if "campaign_id does not match canonical" in message:
        message = f"campaign identity mismatch: {message}"
    if "does not match compact reference" in message:
        message = f"compact receipt reference drift: {message}"
    return DualRunAdmissionError(message)


def _expected(trial_id: str) -> set[str]:
    prefix = f"trials/{trial_id}"
    paths = {
        "campaign_manifest.json",
        "model_field_equivalence_policy.json",
        f"{prefix}/legacy_shadow/execution_receipt.json",
        f"{prefix}/legacy_shadow/legacy_shadow_export.json",
        f"{prefix}/legacy_shadow/lane_evidence.json",
        f"{prefix}/adr0006_candidate/execution_receipt.json",
        f"{prefix}/adr0006_candidate/producer_package/manifest.json",
        f"{prefix}/adr0006_candidate/lane_evidence.json",
    }
    paths.update(
        f"{prefix}/adr0006_candidate/producer_package/{name}"
        for name in S05_FILE_MAP.values()
    )
    return paths


def _fingerprint(stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _path_fingerprint(path: Path) -> tuple[int, int, int, int, int]:
    return _fingerprint(path.lstat())


def _read_stable(path: Path, label: str) -> tuple[bytes, tuple[int, ...]]:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise _fail(f"{label} cannot be opened as a stable regular file") from exc
    try:
        before = os.fstat(fd)
        chunks = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    key = _fingerprint(after)
    if _fingerprint(before) != key or _path_fingerprint(path) != key:
        raise _fail(f"{label} changed during package observation")
    return b"".join(chunks), key


def _canonical(data: bytes, label: str) -> Any:
    try:
        value = json.loads(data)
    except json.JSONDecodeError as exc:
        raise _fail(f"{label} is not readable JSON") from exc
    if data != canonical_json_bytes(value):
        raise _fail(f"{label} is not canonical JSON")
    return value


def observe_s06_package(root: Path, trial_id: str) -> dict[str, Any]:
    """Read each exact S06 package file once and retain the sealed bytes."""
    try:
        trial_id = ensure_trial_id(trial_id)
        supplied = Path(root)
        if not supplied.is_dir() or supplied.is_symlink():
            raise _fail("S06 package root must be a real directory")
        root = supplied.resolve(strict=True)
        files = {}
        for path in root.rglob("*"):
            if path.is_symlink():
                raise _fail("symlinks are denied")
            if path.is_file():
                files[path.relative_to(root).as_posix()] = path
        expected = _expected(trial_id)
        if set(files) != expected | {"SHA256SUMS"}:
            raise _fail("S06 package file set mismatch")

        root_key = _path_fingerprint(root)
        source_bytes, fingerprints = {}, {}
        for relative in sorted(files):
            source_bytes[relative], fingerprints[relative] = _read_stable(
                files[relative], relative
            )
        if _path_fingerprint(root) != root_key:
            raise _fail("S06 package root changed during observation")

        try:
            lines = source_bytes["SHA256SUMS"].decode().splitlines()
        except UnicodeDecodeError as exc:
            raise _fail("SHA256SUMS is not UTF-8") from exc
        sums = {}
        for line in lines:
            try:
                digest, relative = line.split("  ", 1)
            except ValueError as exc:
                raise _fail("SHA256SUMS is malformed") from exc
            ensure_sha256(digest, "SHA256SUMS digest")
            if relative in sums:
                raise _fail("SHA256SUMS contains duplicate paths")
            sums[relative] = digest
        if not lines or list(sums) != sorted(sums) or set(sums) != expected:
            raise _fail("SHA256SUMS does not match the exact sorted file set")

        documents, payload_bytes, observations = {}, {}, []
        for relative in sorted(expected):
            data = source_bytes[relative]
            digest = sha256_bytes(data)
            if sums[relative] != digest:
                raise _fail(f"package digest mismatch: {relative}")
            documents[relative] = _canonical(data, relative)
            payload_bytes[relative] = data
            observations.append(
                {"relative_path": relative, "sha256": digest, "bytes": len(data)}
            )
        file_set_sha256 = sha256_json(observations)
        return {
            "trial_id": trial_id,
            "root_path": root,
            "root_fingerprint": root_key,
            "documents": documents,
            "payload_bytes": payload_bytes,
            "files": observations,
            "fingerprints": fingerprints,
            "file_set_sha256": file_set_sha256,
            "package_sha256": sha256_json(
                {"trial_id": trial_id, "file_set_sha256": file_set_sha256}
            ),
        }
    except DualRunAdmissionError:
        raise
    except DualRunProjectionError as exc:
        raise _projection_failure(exc) from exc
    except OSError as exc:
        raise _fail("S06 package observation failed") from exc


def verify_observed_package_unchanged(observed: Mapping[str, Any]) -> None:
    """Deny publication if any source path changed after the sealed read."""
    record = require_mapping(observed, "observed S06 package")
    root = Path(record["root_path"])
    if not root.is_dir() or root.is_symlink():
        raise _fail("S06 package root changed after admission")
    if _path_fingerprint(root) != tuple(record["root_fingerprint"]):
        raise _fail("S06 package root changed after admission")
    current = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise _fail("S06 package gained a symlink after admission")
        if path.is_file():
            current[path.relative_to(root).as_posix()] = path
    fingerprints = require_mapping(record.get("fingerprints"), "package fingerprints")
    if set(current) != set(fingerprints):
        raise _fail("S06 package file set changed after admission")
    for relative, expected in fingerprints.items():
        try:
            actual = _path_fingerprint(current[str(relative)])
        except OSError as exc:
            raise _fail("S06 package changed after admission") from exc
        if actual != tuple(expected):
            raise _fail(f"S06 package changed after admission: {relative}")


def bind_verified_receipt(
    full: Mapping[str, Any],
    compact: Mapping[str, Any],
    resolver: ReceiptVerificationResolver,
    label: str,
) -> dict[str, Any]:
    """Bind one full receipt to its compact reference and injected H09 result."""
    try:
        _validate_receipt(full, compact, label)
        body = require_mapping(full.get("receipt"), f"{label} body")
        signature = require_mapping(full.get("signature"), f"{label} signature")
        digest = sha256_json(body)
        try:
            result = require_mapping(resolver.resolve(full), f"{label} H09 result")
        except Exception as exc:
            raise _fail(f"{label} H09 verification unavailable") from exc
        required = {
            "verification_receipt_id",
            "verification_receipt_sha256",
            "verifier_revision",
            "run_id",
            "receipt_sha256",
            "key_id",
            "signature_verified",
            "verified_at",
        }
        if set(result) != required:
            raise _fail(f"{label} H09 fields are not exact")
        core = dict(result)
        core.pop("verification_receipt_id")
        core.pop("verification_receipt_sha256")
        core_digest = sha256_json(core)
        if result["verification_receipt_sha256"] != core_digest:
            raise _fail(f"{label} H09 verification digest mismatch")
        if result["verification_receipt_id"] != f"receipt-verification-sha256-{core_digest}":
            raise _fail(f"{label} H09 verification identity mismatch")
        ensure_revision(result["verifier_revision"], "H09 verifier revision")
        if result["signature_verified"] is not True:
            raise _fail(f"{label} H09 verification failed")
        if result["run_id"] != body.get("run_id") or result["receipt_sha256"] != digest:
            raise _fail(f"{label} H09 binding drift")
        if result["key_id"] != signature.get("key_id"):
            raise _fail(f"{label} H09 key binding drift")
        return dict(result)
    except DualRunAdmissionError:
        raise
    except DualRunProjectionError as exc:
        raise _projection_failure(exc) from exc


def _admit(
    observed: Mapping[str, Any],
    expected_campaign: Mapping[str, Any],
    trial_id: str,
    resolver: ReceiptVerificationResolver,
    created_at: str,
) -> dict[str, Any]:
    try:
        trial_id = ensure_trial_id(trial_id)
        docs = require_mapping(observed.get("documents"), "observed documents")
        campaign = validate_campaign(docs["campaign_manifest.json"], trial_id)
        if campaign != validate_campaign(expected_campaign, trial_id):
            raise _fail("staged campaign differs from expected campaign")
        policy = _validate_policy(campaign, docs["model_field_equivalence_policy.json"])
        prefix = f"trials/{trial_id}"
        legacy_full = docs[f"{prefix}/legacy_shadow/execution_receipt.json"]
        export = docs[f"{prefix}/legacy_shadow/legacy_shadow_export.json"]
        legacy_lane = docs[f"{prefix}/legacy_shadow/lane_evidence.json"]
        candidate_full = docs[f"{prefix}/adr0006_candidate/execution_receipt.json"]
        manifest = docs[f"{prefix}/adr0006_candidate/producer_package/manifest.json"]
        candidate_lane = docs[f"{prefix}/adr0006_candidate/lane_evidence.json"]
        collections = {
            key: docs[f"{prefix}/adr0006_candidate/producer_package/{filename}"]
            for key, filename in S05_FILE_MAP.items()
        }
        canonical_legacy_shadow_export_bytes(export)
        checked_manifest, checked_collections = _verify_s05_package(
            campaign, manifest, collections
        )
        expected_legacy = build_legacy_lane_projection_input(
            campaign=campaign,
            trial_id=trial_id,
            legacy_shadow_export=export,
            execution_receipt=legacy_lane["execution_receipt"],
            created_at=legacy_lane["created_at"],
        )
        expected_candidate = build_candidate_lane_projection_input(
            campaign=campaign,
            trial_id=trial_id,
            s05_envelope=checked_manifest,
            s05_collections=checked_collections,
            execution_receipt=candidate_lane["execution_receipt"],
            h06_job_record_id=candidate_lane.get("h06_job_record_id", ""),
            h07_admission_receipt_id=candidate_lane.get("h07_admission_receipt_id", ""),
            created_at=candidate_lane["created_at"],
        )
        if legacy_lane != expected_legacy:
            raise _fail("legacy lane binding to staged export failed")
        if candidate_lane != expected_candidate:
            raise _fail("candidate lane binding to staged package failed")
        for lane in (legacy_lane, candidate_lane):
            if lane.get("schema_violations") != 0 or lane.get(
                "missing_required_provenance"
            ) != 0:
                raise _fail("lane schema or provenance defects block admission")
        verifications = [
            bind_verified_receipt(
                legacy_full, legacy_lane["execution_receipt"], resolver, "legacy receipt"
            ),
            bind_verified_receipt(
                candidate_full,
                candidate_lane["execution_receipt"],
                resolver,
                "candidate receipt",
            ),
        ]
        receipts = [legacy_lane["execution_receipt"], candidate_lane["execution_receipt"]]
        if len({item["run_id"] for item in receipts}) != 2 or len(
            {item["receipt_sha256"] for item in receipts}
        ) != 2:
            raise _fail("legacy and candidate executions must be distinct")
        body: dict[str, Any] = {
            "schema_version": "s07_trial_admission_receipt.v1",
            "trial_admission_id": "",
            "campaign_id": campaign["campaign_id"],
            "campaign_sha256": sha256_json(campaign),
            "trial_id": trial_id,
            "s06_package_sha256": observed["package_sha256"],
            "s06_package_file_set_sha256": observed["file_set_sha256"],
            "source_set_sha256": campaign["source_set_sha256"],
            "pins_sha256": campaign["pins_sha256"],
            "equivalence_policy_id": policy["policy_id"],
            "equivalence_policy_sha256": policy["policy_id"].rsplit("-", 1)[-1],
            "legacy_shadow_export_id": export["legacy_shadow_export_id"],
            "legacy_lane_evidence_id": legacy_lane["lane_evidence_id"],
            "legacy_lane_sha256": sha256_json(legacy_lane),
            "candidate_package_id": checked_manifest["package_id"],
            "candidate_package_sha256": checked_manifest["normalized_digest"],
            "candidate_lane_evidence_id": candidate_lane["lane_evidence_id"],
            "candidate_lane_sha256": sha256_json(candidate_lane),
            "execution_receipts": receipts,
            "receipt_verifications": sorted(verifications, key=lambda item: item["run_id"]),
            "file_accounting": {
                "required": len(_expected(trial_id)),
                "verified": len(observed["files"]),
                "missing": 0,
                "unexpected": 0,
                "failed": 0,
            },
            "receipt_accounting": {"required": 2, "verified": 2, "failed": 0},
            "lane_accounting": {"required": 2, "verified": 2, "blocked": 0},
            "validation_results": [
                "PACKAGE_BYTES_VERIFIED",
                "CAMPAIGN_POLICY_BOUND",
                "LEGACY_LANE_BOUND",
                "CANDIDATE_LANE_BOUND",
                "H09_RECEIPTS_BOUND",
                "LANE_RUNS_SEPARATE",
            ],
            "status": "ADMITTED",
            "reason_codes": [],
            "created_at": created_at,
            "production_mutation_allowed": False,
            "dual_run_executed": False,
            "h08_evaluation_executed": False,
            "certified_state_created": False,
            "active_snapshot_promoted": False,
            "retirement_authorized": False,
        }
        identity = dict(body)
        identity.pop("trial_admission_id")
        body["trial_admission_id"] = "s07-trial-admission-sha256-" + sha256_json(identity)
        return body
    except DualRunAdmissionError:
        raise
    except DualRunProjectionError as exc:
        raise _projection_failure(exc) from exc


def compute_s06_trial_admission_snapshot(
    *,
    package_root: Path,
    expected_campaign: Mapping[str, Any],
    trial_id: str,
    receipt_verification_resolver: ReceiptVerificationResolver,
    created_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the receipt and the single-read immutable source snapshot."""
    observed = observe_s06_package(package_root, trial_id)
    return (
        _admit(
            observed,
            expected_campaign,
            trial_id,
            receipt_verification_resolver,
            created_at,
        ),
        observed,
    )


def compute_s06_trial_admission(
    *,
    package_root: Path,
    expected_campaign: Mapping[str, Any],
    trial_id: str,
    receipt_verification_resolver: ReceiptVerificationResolver,
    created_at: str,
) -> dict[str, Any]:
    """Admit one S06 trial only when every package and receipt binding is exact."""
    return compute_s06_trial_admission_snapshot(
        package_root=package_root,
        expected_campaign=expected_campaign,
        trial_id=trial_id,
        receipt_verification_resolver=receipt_verification_resolver,
        created_at=created_at,
    )[0]


def record_trial_admission_receipt(
    destination_root: Path, receipt: Mapping[str, Any]
) -> Path:
    """Write one immutable trial-admission receipt with replay protection."""
    record = require_mapping(receipt, "trial admission receipt")
    identity = dict(record)
    admission_id = identity.pop("trial_admission_id", "")
    if admission_id != "s07-trial-admission-sha256-" + sha256_json(identity):
        raise _fail("trial admission receipt identity mismatch")
    path = (
        Path(destination_root)
        / "registry"
        / "s07_trial_admissions"
        / f"{admission_id}.json"
    )
    data = canonical_json_bytes(record)
    if path.exists():
        if path.read_bytes() != data:
            raise _fail("trial admission replay conflict")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


__all__ = [
    "DualRunAdmissionError",
    "ReceiptVerificationResolver",
    "S05_FILE_MAP",
    "bind_verified_receipt",
    "compute_s06_trial_admission",
    "compute_s06_trial_admission_snapshot",
    "observe_s06_package",
    "record_trial_admission_receipt",
    "verify_observed_package_unchanged",
]
