"""Deterministic offline S07 campaign handoff to later H08 evaluation."""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from . import _validate_contract
from ._dual_run_common import (
    canonical_json_bytes,
    require_mapping,
    sha256_bytes,
    sha256_json,
    validate_campaign,
)
from .dual_run_admission import (
    DualRunAdmissionError,
    ReceiptVerificationResolver,
    bind_verified_receipt,
    compute_s06_trial_admission_snapshot,
    verify_observed_package_unchanged,
)
from .dual_run_projection import _validate_policy as _validate_staged_policy

ACTION = "RELEASE_TO_H08_OFFLINE_EVALUATION"


def _fail(message: str) -> DualRunAdmissionError:
    return DualRunAdmissionError(message)


def compute_handoff_request_sha256(
    *,
    campaign: Mapping[str, Any],
    policy: Mapping[str, Any],
    trial_admissions: Sequence[Mapping[str, Any]],
    rollback_evidence: Mapping[str, Any],
) -> str:
    return sha256_json(
        {
            "campaign_sha256": sha256_json(campaign),
            "policy_sha256": sha256_json(policy),
            "trial_admissions": sorted(
                (
                    {
                        "trial_id": item["trial_id"],
                        "trial_admission_id": item["trial_admission_id"],
                        "s06_package_sha256": item["s06_package_sha256"],
                    }
                    for item in trial_admissions
                ),
                key=lambda item: item["trial_id"],
            ),
            "rollback_evidence_sha256": sha256_json(rollback_evidence),
        }
    )


def compute_operator_authorization_id(authorization: Mapping[str, Any]) -> str:
    body = dict(authorization)
    body.pop("authorization_id", None)
    body.pop("signature", None)
    return "s07-operator-authorization-sha256-" + sha256_json(body)


def compute_rollback_evidence_id(rollback: Mapping[str, Any]) -> str:
    body = dict(rollback)
    body.pop("rollback_evidence_id", None)
    return "rollback-drill-sha256-" + sha256_json(body)


def _validate_policy(
    policy: Mapping[str, Any],
    campaign: Mapping[str, Any],
    admissions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    record = _validate_contract(
        require_mapping(policy, "equivalence policy"),
        "tests/fixtures/thehub_h08/model_field_equivalence_policy.v1.schema.json",
        "equivalence policy",
    )
    record = _validate_staged_policy(campaign, record)
    required = set(map(str, campaign.get("required_model_fields", [])))
    fields = [str(item["field_key"]) for item in record["rules"]]
    if len(fields) != len(set(fields)) or set(fields) != required:
        raise _fail("equivalence policy model-field coverage mismatch")
    policy_id = record["policy_id"]
    policy_sha = policy_id.rsplit("-", 1)[-1]
    for admission in admissions:
        if (
            admission.get("equivalence_policy_id") != policy_id
            or admission.get("equivalence_policy_sha256") != policy_sha
        ):
            raise _fail("trial admission equivalence policy binding mismatch")
    return record


def validate_operator_authorization(
    authorization: Mapping[str, Any],
    *,
    campaign: Mapping[str, Any],
    handoff_request_sha256: str,
    evaluated_at: str,
) -> dict[str, Any]:
    record = _validate_contract(
        require_mapping(authorization, "operator authorization"),
        "schemas/ai_imagery/s07_operator_handoff_authorization.v1.schema.json",
        "operator authorization",
    )
    if record["authorized_action"] != ACTION:
        raise _fail("operator authorization scope is prohibited")
    if record["decision"] == "ABORT":
        raise _fail("operator authorization aborted")
    if record["decision"] != "APPROVE":
        raise _fail("operator authorization is not approved")
    if (
        record["campaign_id"] != campaign["campaign_id"]
        or record["campaign_sha256"] != sha256_json(campaign)
    ):
        raise _fail("operator authorization campaign binding mismatch")
    if record["handoff_request_sha256"] != handoff_request_sha256:
        raise _fail("operator authorization handoff binding mismatch")
    if record["authorization_id"] != compute_operator_authorization_id(record):
        raise _fail("operator authorization identity mismatch")
    signature = record["signature"]
    body = dict(record)
    body.pop("signature")
    if signature["payload_sha256"] != sha256_json(body):
        raise _fail("operator signature binding mismatch")
    try:
        issued = datetime.fromisoformat(record["issued_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
        evaluated = datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _fail("operator authorization timestamp is invalid") from exc
    if expires <= issued or expires <= evaluated:
        raise _fail("operator authorization expired")
    return record


def _validate_rollback(
    rollback: Mapping[str, Any], campaign: Mapping[str, Any]
) -> dict[str, Any]:
    record = _validate_contract(
        require_mapping(rollback, "rollback evidence"),
        "tests/fixtures/thehub_h08/rollback_drill_evidence.v1.schema.json",
        "rollback evidence",
    )
    if record["rollback_evidence_id"] != compute_rollback_evidence_id(record):
        raise _fail("rollback evidence identity mismatch")
    if record["campaign_id"] != campaign["campaign_id"]:
        raise _fail("rollback campaign binding mismatch")
    if record["unexpected_writes"]:
        raise _fail("rollback contains unexpected writes")
    if not record["checks"] or not all(value is True for value in record["checks"].values()):
        raise _fail("rollback checks are incomplete")
    receipt = record["execution_receipt"]
    if receipt["status"] not in {"rolled_back", "succeeded"} or (
        receipt["rollback_state"] != "succeeded"
    ):
        raise _fail("rollback did not succeed")
    if receipt["signature_verified"] is not True:
        raise _fail("rollback receipt is not verified")
    return record


def _lane(snapshot: Mapping[str, Any], trial_id: str, lane: str) -> dict[str, Any]:
    directory = "legacy_shadow" if lane == "LEGACY_SHADOW" else "adr0006_candidate"
    documents = require_mapping(snapshot.get("documents"), "snapshot documents")
    return dict(documents[f"trials/{trial_id}/{directory}/lane_evidence.json"])


def _payload_files(
    *,
    campaign: Mapping[str, Any],
    policy: Mapping[str, Any],
    rollback: Mapping[str, Any],
    authorization: Mapping[str, Any],
    admissions: Sequence[Mapping[str, Any]],
    snapshots: Mapping[str, Mapping[str, Any]],
    rollback_verification: Mapping[str, Any],
) -> dict[str, bytes]:
    files = {
        "campaign_manifest.json": canonical_json_bytes(campaign),
        "model_field_equivalence_policy.json": canonical_json_bytes(policy),
        "rollback_drill_evidence.json": canonical_json_bytes(rollback),
        "operator_handoff_authorization.json": canonical_json_bytes(authorization),
    }
    verifications = {
        rollback_verification["verification_receipt_id"]: rollback_verification
    }
    for admission in sorted(admissions, key=lambda item: item["trial_id"]):
        trial_id = admission["trial_id"]
        files[f"trial_admissions/{trial_id}.json"] = canonical_json_bytes(admission)
        for lane_kind in ("LEGACY_SHADOW", "ADR0006_CANDIDATE"):
            directory = (
                "legacy_shadow" if lane_kind == "LEGACY_SHADOW" else "adr0006_candidate"
            )
            files[f"trials/{trial_id}/{directory}/lane_evidence.json"] = (
                canonical_json_bytes(_lane(snapshots[trial_id], trial_id, lane_kind))
            )
        for verification in admission["receipt_verifications"]:
            verifications[verification["verification_receipt_id"]] = verification
    for identity, verification in sorted(verifications.items()):
        files[f"receipt_verifications/{identity}.json"] = canonical_json_bytes(
            verification
        )
    return files


def _unique(
    admissions: Sequence[Mapping[str, Any]],
    rollback_compact: Mapping[str, Any],
    rollback_verification: Mapping[str, Any],
) -> None:
    receipts = [
        receipt for admission in admissions for receipt in admission["execution_receipts"]
    ] + [rollback_compact]
    if len({item["run_id"] for item in receipts}) != len(receipts):
        raise _fail("duplicate execution run ID across handoff")
    if len({item["receipt_sha256"] for item in receipts}) != len(receipts):
        raise _fail("duplicate execution receipt SHA-256 across handoff")
    verifications = [
        item for admission in admissions for item in admission["receipt_verifications"]
    ] + [rollback_verification]
    if len({item["verification_receipt_id"] for item in verifications}) != len(
        verifications
    ):
        raise _fail("duplicate H09 verification receipt ID across handoff")
    if len({item["verification_receipt_sha256"] for item in verifications}) != len(
        verifications
    ):
        raise _fail("duplicate H09 verification receipt SHA-256 across handoff")


def _write_files(root: Path, files: Mapping[str, bytes]) -> None:
    for relative, data in sorted(files.items()):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def build_h08_operator_handoff(
    *,
    destination_root: Path,
    campaign: Mapping[str, Any],
    equivalence_policy: Mapping[str, Any],
    trial_admissions: Sequence[Mapping[str, Any]],
    trial_package_roots: Mapping[str, Path],
    rollback_evidence: Mapping[str, Any],
    rollback_full_receipt: Mapping[str, Any],
    rollback_verification_resolver: ReceiptVerificationResolver,
    operator_authorization: Mapping[str, Any] | None,
    created_at: str,
) -> dict[str, Any]:
    raw_trials = sorted(str(item["trial_id"]) for item in campaign.get("trials", []))
    if not raw_trials:
        raise _fail("campaign trial set is empty")
    campaign_record = validate_campaign(campaign, raw_trials[0])
    expected_trials = sorted(item["trial_id"] for item in campaign_record["trials"])
    if len(expected_trials) < 2:
        raise _fail("campaign requires at least two trials")
    admission_map = {str(item.get("trial_id")): item for item in trial_admissions}
    if set(admission_map) != set(expected_trials) or len(admission_map) != len(
        trial_admissions
    ):
        raise _fail("trial admission set is incomplete or additional")
    if set(trial_package_roots) != set(expected_trials):
        raise _fail("trial package root set is incomplete or additional")

    admissions, snapshots = [], {}
    for trial_id in expected_trials:
        resolver = _ReplayResolver(admission_map[trial_id]["receipt_verifications"])
        current, snapshot = compute_s06_trial_admission_snapshot(
            package_root=trial_package_roots[trial_id],
            expected_campaign=campaign_record,
            trial_id=trial_id,
            receipt_verification_resolver=resolver,
            created_at=admission_map[trial_id]["created_at"],
        )
        if current != admission_map[trial_id]:
            raise _fail("trial admission does not match revalidated package")
        admissions.append(current)
        snapshots[trial_id] = snapshot

    policy = _validate_policy(equivalence_policy, campaign_record, admissions)
    rollback = _validate_rollback(rollback_evidence, campaign_record)
    rollback_compact = {
        key: rollback["execution_receipt"][key]
        for key in ("run_id", "receipt_sha256", "signature_verified")
    }
    rollback_verification = bind_verified_receipt(
        rollback_full_receipt,
        rollback_compact,
        rollback_verification_resolver,
        "rollback receipt",
    )
    _unique(admissions, rollback_compact, rollback_verification)
    request_digest = compute_handoff_request_sha256(
        campaign=campaign_record,
        policy=policy,
        trial_admissions=admissions,
        rollback_evidence=rollback,
    )
    if operator_authorization is None:
        raise _fail("operator authorization is required")
    authorization = validate_operator_authorization(
        operator_authorization,
        campaign=campaign_record,
        handoff_request_sha256=request_digest,
        evaluated_at=created_at,
    )
    files = _payload_files(
        campaign=campaign_record,
        policy=policy,
        rollback=rollback,
        authorization=authorization,
        admissions=admissions,
        snapshots=snapshots,
        rollback_verification=rollback_verification,
    )
    observations = [
        {"relative_path": path, "sha256": sha256_bytes(data), "bytes": len(data)}
        for path, data in sorted(files.items())
    ]
    lanes = [
        _lane(snapshots[trial], trial, lane)
        for trial in expected_trials
        for lane in ("LEGACY_SHADOW", "ADR0006_CANDIDATE")
    ]
    receipt_refs = sorted(
        [receipt for admission in admissions for receipt in admission["execution_receipts"]]
        + [rollback_compact],
        key=lambda item: item["run_id"],
    )
    verification_refs = sorted(
        [
            {
                "verification_receipt_id": item["verification_receipt_id"],
                "verification_receipt_sha256": item["verification_receipt_sha256"],
            }
            for admission in admissions
            for item in admission["receipt_verifications"]
        ]
        + [
            {
                "verification_receipt_id": rollback_verification[
                    "verification_receipt_id"
                ],
                "verification_receipt_sha256": rollback_verification[
                    "verification_receipt_sha256"
                ],
            }
        ],
        key=lambda item: item["verification_receipt_id"],
    )
    manifest: dict[str, Any] = {
        "schema_version": "s07_h08_handoff_manifest.v1",
        "handoff_id": "",
        "campaign_id": campaign_record["campaign_id"],
        "campaign_sha256": sha256_json(campaign_record),
        "equivalence_policy_id": policy["policy_id"],
        "equivalence_policy_sha256": policy["policy_id"].rsplit("-", 1)[-1],
        "trial_admission_ids": sorted(item["trial_admission_id"] for item in admissions),
        "trial_package_sha256s": sorted(item["s06_package_sha256"] for item in admissions),
        "lane_evidence_ids": sorted(item["lane_evidence_id"] for item in lanes),
        "lane_evidence_sha256s": sorted(sha256_json(item) for item in lanes),
        "execution_receipt_references": receipt_refs,
        "h09_verification_receipt_references": verification_refs,
        "rollback_evidence_sha256": sha256_json(rollback),
        "operator_authorization_id": authorization["authorization_id"],
        "operator_authorization_sha256": sha256_json(authorization),
        "handoff_request_sha256": request_digest,
        "file_manifest": observations,
        "file_set_sha256": sha256_json(observations),
        "trial_accounting": {
            "required": len(expected_trials),
            "admitted": len(admissions),
            "blocked": 0,
            "aborted": 0,
        },
        "lane_accounting": {
            "required": len(lanes),
            "verified": len(lanes),
            "blocked": 0,
            "not_evaluated": len(lanes),
        },
        "receipt_accounting": {
            "required": len(receipt_refs),
            "verified": len(receipt_refs),
            "rejected": 0,
            "unresolved": 0,
        },
        "created_at": created_at,
        "status": "RELEASED_TO_H08",
        "production_mutation_allowed": False,
        "dual_run_executed": False,
        "h08_evaluation_executed": False,
        "certified_state_created": False,
        "active_snapshot_promoted": False,
        "retirement_authorized": False,
    }
    identity = dict(manifest)
    identity.pop("handoff_id")
    manifest["handoff_id"] = "s07-h08-handoff-sha256-" + sha256_json(identity)
    files["H08_HANDOFF.json"] = canonical_json_bytes(manifest)
    files["SHA256SUMS"] = "".join(
        f"{sha256_bytes(data)}  {path}\n" for path, data in sorted(files.items())
    ).encode()

    for snapshot in snapshots.values():
        verify_observed_package_unchanged(snapshot)
    destination = Path(destination_root)
    if destination.is_symlink():
        raise _fail("handoff destination symlink is denied")
    if destination.exists():
        existing = {
            path.relative_to(destination).as_posix(): path.read_bytes()
            for path in destination.rglob("*")
            if path.is_file()
        }
        if existing != files:
            raise _fail("handoff replay conflict")
        return manifest
    temporary = destination.parent / f".{destination.name}.s07-tmp"
    if temporary.exists() or temporary.is_symlink():
        raise _fail("handoff temporary destination already exists")
    try:
        _write_files(temporary, files)
        os.replace(temporary, destination)
    except Exception:
        if temporary.exists() and not temporary.is_symlink():
            shutil.rmtree(temporary)
        raise
    return manifest


class _ReplayResolver:
    def __init__(self, records: Sequence[Mapping[str, Any]]) -> None:
        self._records = {}
        for record in records:
            run_id = str(record["run_id"])
            if run_id in self._records:
                raise _fail("duplicate H09 replay binding")
            self._records[run_id] = record

    def resolve(self, full_receipt: Mapping[str, Any]) -> Mapping[str, Any]:
        run_id = str(require_mapping(full_receipt.get("receipt"), "receipt")["run_id"])
        try:
            return self._records[run_id]
        except KeyError as exc:
            raise _fail("missing H09 replay binding") from exc
