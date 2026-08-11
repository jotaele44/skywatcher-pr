from __future__ import annotations

from copy import deepcopy

from skywatcher.ai_imagery._dual_run_common import (
    compute_campaign_id,
    compute_pins_sha256,
    compute_source_set_sha256,
    sha256_json,
)
from skywatcher.ai_imagery.dual_run_projection import S05_OUTPUT_IDS

SKYWATCHER_REVISION = "3b7ef00006a85c49c88bbbd129f662392fb2f370"
THEHUB_REVISION = "d4b849c0e6d4ab01584c0f4eed32267a3663ca99"
CREATED_AT = "2026-07-31T14:00:00Z"


def campaign() -> dict:
    pins = {
        "schema_revisions": {"aviation_vision_extraction.v1": "1" * 64},
        "provider_id": "legacy-provider",
        "model_id": "vision-model",
        "model_revision": "vision-model-r1",
        "prompt_template_version": "fr24-v1",
        "prompt_template_hash": "2" * 64,
        "policy_version": "egress-v1",
        "policy_hash": "3" * 64,
        "worker_profile_id": "shadow-worker",
        "worker_profile_version": "v1",
        "worker_profile_hash": "4" * 64,
        "equivalence_policy_id": "model-equivalence-policy-sha256-" + "5" * 64,
        "equivalence_policy_sha256": "5" * 64,
    }
    record = {
        "schema_version": "dual_run_campaign_manifest.v1",
        "campaign_id": "",
        "thehub_revision": THEHUB_REVISION,
        "skywatcher_revision": SKYWATCHER_REVISION,
        "source_artifacts": [
            {"artifact_id": "artifact-sha256-" + "a" * 64, "sha256": "a" * 64, "classification": "TEST_ONLY"},
            {"artifact_id": "artifact-sha256-" + "b" * 64, "sha256": "b" * 64, "classification": "TEST_ONLY"},
            {"artifact_id": "artifact-sha256-" + "c" * 64, "sha256": "c" * 64, "classification": "TEST_ONLY"},
        ],
        "source_set_sha256": "",
        "pins": pins,
        "pins_sha256": "",
        "trials": [{"trial_id": "trial-01"}, {"trial_id": "trial-02"}],
        "required_deterministic_outputs": sorted(S05_OUTPUT_IDS),
        "required_model_fields": ["artifact-a:registration"],
        "production_mutation_allowed": False,
        "retirement_authorized": False,
        "created_at": CREATED_AT,
    }
    record["source_set_sha256"] = compute_source_set_sha256(record)
    record["pins_sha256"] = compute_pins_sha256(record)
    record["campaign_id"] = compute_campaign_id(record)
    return record


def execution_receipt_ref(seed: str = "1") -> dict:
    return {
        "run_id": seed * 32,
        "receipt_sha256": seed * 64,
        "signature_verified": True,
    }


def s05_package() -> tuple[dict, dict]:
    source_a = "artifact-sha256-" + "a" * 64
    source_b = "artifact-sha256-" + "b" * 64
    source_c = "artifact-sha256-" + "c" * 64
    collections = {
        "source_artifacts": deepcopy(campaign()["source_artifacts"]),
        "aviation_extractions": [
            {
                "schema_version": "aviation_vision_extraction.v1",
                "extraction_id": "extract-1",
                "source_artifact_id": source_a,
                "model_run_receipt_id": "receipt-1",
                "extraction_schema_version": "aviation-fields.v1",
                "fields": [
                    {
                        "field_name": "registration",
                        "value": "N999ZY",
                        "provenance_id": "field-1",
                        "validation_outcome": "VALID",
                    }
                ],
                "review_status": "NEEDS_REVIEW",
                "provisional": True,
            }
        ],
        "model_field_provenance": [
            {
                "field_id": "field-1",
                "field_key": "artifact-a:registration",
                "model_run_receipt_id": "receipt-1",
                "source_artifact_id": source_a,
                "source_sha256": "a" * 64,
                "provider_id": "legacy-provider",
                "model_id": "vision-model",
                "model_revision": "vision-model-r1",
                "prompt_template_hash": "2" * 64,
                "policy_version": "egress-v1",
                "access_context_hash": "6" * 64,
                "extraction_schema_version": "aviation-fields.v1",
                "review_status": "REVIEWED",
            }
        ],
        "provisional_signals": [
            {
                "schema_version": "satim_provisional_signal.v1",
                "signal_id": "signal-1",
                "source_artifact_ids": [source_b],
                "provisional": True,
            }
        ],
        "processing_receipts": [{"receipt_id": "receipt-1", "outcome": "SUCCEEDED"}],
        "exclusions": [{"source_artifact_id": source_c, "reason": "unsupported_media"}],
        "failures": [],
    }
    accounting = {"inputs": 3, "excluded": 1, "failed": 0, "outputs": 2}
    digest_payload = {
        "schema_version": "skywatcher_producer_package.v2",
        "producer_revision": SKYWATCHER_REVISION,
        "collections": collections,
        "accounting": accounting,
    }
    digest = sha256_json(digest_payload)
    envelope = {
        "schema_version": "skywatcher_producer_package.v2",
        "package_id": "skywatcher-package-" + digest[:24],
        "producer_revision": SKYWATCHER_REVISION,
        "created_at": CREATED_AT,
        "source_artifact_ids": sorted(item["artifact_id"] for item in collections["source_artifacts"]),
        "aviation_extraction_ids": ["extract-1"],
        "model_field_provenance_ids": ["field-1"],
        "provisional_signal_ids": ["signal-1"],
        "processing_receipt_ids": ["receipt-1"],
        "accounting": accounting,
        "normalized_digest": digest,
        "certified": False,
    }
    return envelope, collections


def legacy_normalized_records() -> dict:
    return {
        "csv_rows": [
            {
                "id": "legacy-row-1",
                "source_artifact_id": "artifact-sha256-" + "a" * 64,
                "registration": "N999ZY",
                "image_path": "inputs/a.heic",
            }
        ],
        "checkpoint_entries": [
            {
                "source_artifact_id": "artifact-sha256-" + "a" * 64,
                "status": "processed",
            }
        ],
        "log_records": [{"log_id": "legacy-log-1", "message": "completed"}],
    }


def legacy_model_fields() -> list[dict]:
    return [
        {
            "field_key": "artifact-a:registration",
            "value": "N999ZY",
            "provenance": {
                "model_run_receipt_id": "receipt-1",
                "source_artifact_id": "artifact-sha256-" + "a" * 64,
                "source_sha256": "a" * 64,
                "provider_id": "legacy-provider",
                "model_id": "vision-model",
                "model_revision": "vision-model-r1",
                "prompt_template_hash": "2" * 64,
                "policy_version": "egress-v1",
                "access_context_hash": "6" * 64,
                "extraction_schema_version": "aviation-fields.v1",
            },
            "review_status": "REVIEWED",
        }
    ]


def dispositions() -> list[dict]:
    return [
        {"source_artifact_id": "artifact-sha256-" + "a" * 64, "status": "PROCESSED", "reason": "legacy extraction produced output"},
        {"source_artifact_id": "artifact-sha256-" + "b" * 64, "status": "PROCESSED", "reason": "legacy SATIM output produced"},
        {"source_artifact_id": "artifact-sha256-" + "c" * 64, "status": "EXCLUDED", "reason": "unsupported media"},
    ]
