from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from s06_support import (
    CREATED_AT,
    SKYWATCHER_REVISION,
    dispositions,
    legacy_model_fields,
    legacy_normalized_records,
    s05_package,
)
from s06_support import campaign as s06_campaign
from skywatcher.ai_imagery._dual_run_common import (
    compute_campaign_id,
    compute_pins_sha256,
    sha256_json,
)
from skywatcher.ai_imagery.dual_run_handoff import (
    compute_handoff_request_sha256,
    compute_operator_authorization_id,
    compute_rollback_evidence_id,
)
from skywatcher.ai_imagery.dual_run_projection import (
    build_candidate_lane_projection_input,
    build_legacy_lane_projection_input,
    project_s05_deterministic_outputs,
    write_dual_run_evidence_staging,
)
from skywatcher.ai_imagery.legacy_shadow_export import build_legacy_shadow_export

NOW = "2026-07-31T17:00:00Z"
VERIFIER = "9" * 40


def policy() -> dict[str, Any]:
    value = {
        "schema_version": "model_field_equivalence_policy.v1",
        "policy_id": "",
        "version": "1.0.0",
        "rules": [
            {
                "field_key": "artifact-a:registration",
                "comparator": "EXACT_CANONICAL",
                "parameters": {},
            }
        ],
        "created_at": NOW,
    }
    body = dict(value)
    body.pop("policy_id")
    value["policy_id"] = "model-equivalence-policy-sha256-" + sha256_json(body)
    return value


def campaign() -> dict[str, Any]:
    value = s06_campaign()
    equivalence_policy = policy()
    value["trials"] = [{"trial_id": "trial-1"}, {"trial_id": "trial-2"}]
    value["pins"]["equivalence_policy_id"] = equivalence_policy["policy_id"]
    value["pins"]["equivalence_policy_sha256"] = equivalence_policy[
        "policy_id"
    ].rsplit("-", 1)[-1]
    value["pins_sha256"] = compute_pins_sha256(value)
    value["campaign_id"] = compute_campaign_id(value)
    return value


def full_receipt(run_id: str, lane: str) -> dict[str, Any]:
    body = {
        "run_id": run_id,
        "lane": lane,
        "status": "succeeded",
        "completed_at": NOW,
    }
    return {
        "receipt": body,
        "signature": {
            "key_id": f"key-{lane}",
            "algorithm": "Ed25519",
            "value": "detached-signature",
            "payload_sha256": sha256_json(body),
        },
    }


def compact(full: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "run_id": full["receipt"]["run_id"],
        "receipt_sha256": sha256_json(full["receipt"]),
        "signature_verified": True,
    }


class Resolver:
    def __init__(
        self,
        *,
        fail: bool = False,
        drift_run: bool = False,
        verified_at: str = NOW,
    ) -> None:
        self.fail = fail
        self.drift_run = drift_run
        self.verified_at = verified_at

    def resolve(self, full: Mapping[str, Any]) -> dict[str, Any]:
        body = full["receipt"]
        signature = full["signature"]
        core = {
            "verifier_revision": VERIFIER,
            "run_id": "f" * 32 if self.drift_run else body["run_id"],
            "receipt_sha256": sha256_json(body),
            "key_id": signature["key_id"],
            "signature_verified": not self.fail,
            "verified_at": self.verified_at,
        }
        digest = sha256_json(core)
        return {
            "verification_receipt_id": f"receipt-verification-sha256-{digest}",
            "verification_receipt_sha256": digest,
            **core,
        }


def build_s06_package(
    root: Path,
    campaign_value: Mapping[str, Any],
    trial_id: str,
) -> dict[str, Any]:
    ordinal = 1 if trial_id == "trial-1" else 3
    legacy_full = full_receipt(f"{ordinal:032x}", "legacy")
    candidate_full = full_receipt(f"{ordinal + 1:032x}", "candidate")
    envelope, collections = s05_package()
    outputs = project_s05_deterministic_outputs(envelope, collections)
    export = build_legacy_shadow_export(
        campaign=campaign_value,
        trial_id=trial_id,
        created_at=CREATED_AT,
        execution_receipt=compact(legacy_full),
        engine={
            "engine_id": "legacy-shadow",
            "engine_revision": SKYWATCHER_REVISION,
        },
        normalized_legacy_records=legacy_normalized_records(),
        source_artifacts=deepcopy(campaign_value["source_artifacts"]),
        dispositions=dispositions(),
        deterministic_outputs=outputs,
        model_fields=legacy_model_fields(),
        historical_artifacts=[],
    )
    legacy_lane = build_legacy_lane_projection_input(
        campaign=campaign_value,
        trial_id=trial_id,
        legacy_shadow_export=export,
        execution_receipt=compact(legacy_full),
        created_at=CREATED_AT,
    )
    candidate_lane = build_candidate_lane_projection_input(
        campaign=campaign_value,
        trial_id=trial_id,
        s05_envelope=envelope,
        s05_collections=collections,
        execution_receipt=compact(candidate_full),
        h06_job_record_id=f"h06-{trial_id}",
        h07_admission_receipt_id=f"h07-{trial_id}",
        created_at=CREATED_AT,
    )
    write_dual_run_evidence_staging(
        root=root,
        campaign=campaign_value,
        equivalence_policy=policy(),
        trial_id=trial_id,
        legacy_execution_receipt=legacy_full,
        legacy_shadow_export=export,
        legacy_lane=legacy_lane,
        candidate_execution_receipt=candidate_full,
        s05_envelope=envelope,
        s05_collections=collections,
        candidate_lane=candidate_lane,
    )
    return {
        "legacy_full": legacy_full,
        "candidate_full": candidate_full,
    }


def rollback(
    campaign_value: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    full = full_receipt("5" * 32, "rollback")
    value = {
        "schema_version": "rollback_drill_evidence.v1",
        "rollback_evidence_id": "",
        "campaign_id": campaign_value["campaign_id"],
        "pre_state_sha256": "e" * 64,
        "post_state_sha256": "f" * 64,
        "approved_deltas": ["candidate route disabled"],
        "failure_injection_id": "forced-candidate-failure-v1",
        "authorization_reference": "auth://rollback/1",
        "execution_receipt": {
            **compact(full),
            "status": "rolled_back",
            "rollback_state": "succeeded",
        },
        "attestations": [],
        "unexpected_writes": [],
        "checks": {
            "legacy_path_restored": True,
            "candidate_path_disabled": True,
            "immutable_evidence_preserved": True,
        },
        "logs": [{"logical_name": "rollback.log", "sha256": "1" * 64}],
        "created_at": NOW,
        "retirement_authorized": False,
    }
    value["rollback_evidence_id"] = compute_rollback_evidence_id(value)
    return value, full


def authorization(
    campaign_value: Mapping[str, Any],
    policy_value: Mapping[str, Any],
    admissions: list[Mapping[str, Any]],
    rollback_value: Mapping[str, Any],
    *,
    decision: str = "APPROVE",
    action: str = "RELEASE_TO_H08_OFFLINE_EVALUATION",
    expires_at: str = "2026-08-01T17:00:00Z",
) -> dict[str, Any]:
    value = {
        "schema_version": "s07_operator_handoff_authorization.v1",
        "authorization_id": "",
        "campaign_id": campaign_value["campaign_id"],
        "campaign_sha256": sha256_json(campaign_value),
        "handoff_request_sha256": compute_handoff_request_sha256(
            campaign=campaign_value,
            policy=policy_value,
            trial_admissions=admissions,
            rollback_evidence=rollback_value,
        ),
        "authorized_action": action,
        "decision": decision,
        "operator_id": "operator-1",
        "authorization_reference": "auth://s07/1",
        "audit_event_reference": "audit://s07/1",
        "issued_at": "2026-07-31T16:00:00Z",
        "expires_at": expires_at,
        "reason": "Release sealed evidence to offline H08 evaluation.",
        "signature": {},
    }
    value["authorization_id"] = compute_operator_authorization_id(value)
    body = dict(value)
    body.pop("signature")
    value["signature"] = {
        "key_id": "operator-key-1",
        "algorithm": "Ed25519",
        "value": "operator-signature",
        "payload_sha256": sha256_json(body),
        "signature_verified": True,
    }
    return value
