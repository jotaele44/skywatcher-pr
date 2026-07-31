"""Pure H08 lane projection and deterministic staging for ADR 0006 S06."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ._dual_run_common import (
    DualRunProjectionError,
    canonical_json_bytes,
    reject_secret_or_unsafe_paths,
    require_list,
    require_mapping,
    sha256_bytes,
    sha256_json,
    unique_index,
    validate_campaign,
    validate_execution_receipt_ref,
    validate_provenance,
)
from .legacy_shadow_export import (
    canonical_legacy_shadow_export_bytes,
    compute_legacy_shadow_export_id,
)

S05_FILE_MAP = {
    "source_artifacts": "source_artifacts.json",
    "aviation_extractions": "aviation_extractions.json",
    "model_field_provenance": "model_field_provenance.json",
    "provisional_signals": "provisional_signals.json",
    "processing_receipts": "processing_receipts.json",
    "exclusions": "exclusions.json",
    "failures": "failures.json",
}
S05_OUTPUT_IDS = frozenset({"manifest.json", *S05_FILE_MAP.values()})


def lane_evidence_identity_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    payload.pop("lane_evidence_id", None)
    return payload


def compute_lane_evidence_id(record: Mapping[str, Any]) -> str:
    return "dual-run-lane-sha256-" + sha256_json(lane_evidence_identity_payload(record))


def _validate_exact_required_outputs(campaign: Mapping[str, Any]) -> None:
    required = {
        str(value)
        for value in require_list(
            campaign.get("required_deterministic_outputs"),
            "campaign required deterministic outputs",
        )
    }
    if required != S05_OUTPUT_IDS:
        raise DualRunProjectionError(
            "campaign deterministic output set must equal the complete S05 package file set"
        )


def build_legacy_lane_projection_input(
    *,
    campaign: Mapping[str, Any],
    trial_id: str,
    legacy_shadow_export: Mapping[str, Any],
    execution_receipt: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    """Project a validated legacy export into the H08 lane-evidence shape."""
    campaign_record = validate_campaign(campaign, trial_id)
    _validate_exact_required_outputs(campaign_record)
    export = require_mapping(legacy_shadow_export, "legacy shadow export")
    if export.get("legacy_shadow_export_id") != compute_legacy_shadow_export_id(export):
        raise DualRunProjectionError("legacy shadow export identity mismatch")
    if export.get("campaign_id") != campaign_record["campaign_id"]:
        raise DualRunProjectionError("legacy export campaign binding mismatch")
    if export.get("trial_id") != trial_id:
        raise DualRunProjectionError("legacy export trial binding mismatch")
    if export.get("source_set_sha256") != campaign_record["source_set_sha256"]:
        raise DualRunProjectionError("legacy export source-set drift")
    if export.get("pins_sha256") != campaign_record["pins_sha256"]:
        raise DualRunProjectionError("legacy export pin-set drift")
    receipt = validate_execution_receipt_ref(execution_receipt)
    export_receipt = require_mapping(export.get("execution_receipt"), "legacy export receipt")
    if export_receipt != {
        "run_id": receipt["run_id"],
        "receipt_sha256": receipt["receipt_sha256"],
    }:
        raise DualRunProjectionError("legacy export execution-receipt binding mismatch")

    outputs = require_list(export.get("deterministic_outputs"), "legacy deterministic outputs")
    export_fields = require_list(export.get("model_fields"), "legacy model fields")
    fields: list[dict[str, Any]] = []
    for raw_field in export_fields:
        field = require_mapping(raw_field, "legacy model field")
        provenance = require_mapping(field.get("provenance"), "legacy model provenance")
        if not str(provenance.get("model_run_receipt_id") or ""):
            raise DualRunProjectionError("legacy model_run_receipt_id is required")
        fields.append(
            {
                "field_key": field["field_key"],
                "value": field.get("value"),
                "provenance": {
                    key: provenance[key]
                    for key in (
                        "source_artifact_id",
                        "source_sha256",
                        "provider_id",
                        "model_id",
                        "model_revision",
                        "prompt_template_hash",
                        "policy_version",
                        "access_context_hash",
                        "extraction_schema_version",
                    )
                },
                "review_status": field["review_status"],
            }
        )
    input_accounting = require_mapping(export.get("input_accounting"), "legacy input accounting")
    output_accounting = require_mapping(export.get("output_accounting"), "legacy output accounting")
    payload: dict[str, Any] = {
        "schema_version": "dual_run_lane_evidence.v1",
        "lane_evidence_id": "",
        "campaign_id": campaign_record["campaign_id"],
        "trial_id": trial_id,
        "lane": "LEGACY_SHADOW",
        "execution_receipt": receipt,
        "source_set_sha256": campaign_record["source_set_sha256"],
        "pins_sha256": campaign_record["pins_sha256"],
        "legacy_shadow_export_id": export["legacy_shadow_export_id"],
        "deterministic_outputs": outputs,
        "model_fields": fields,
        "schema_violations": 0,
        "missing_required_provenance": 0,
        "input_accounting": input_accounting,
        "output_accounting": output_accounting,
        "certified_state_created": False,
        "active_snapshot_promoted": False,
        "answer_eligible": False,
        "created_at": created_at,
    }
    reject_secret_or_unsafe_paths(payload, path="legacy_lane_projection")
    payload["lane_evidence_id"] = compute_lane_evidence_id(payload)
    return payload


def _canonicalize_s05_collections(
    collections: Mapping[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    source = require_mapping(collections, "S05 collections")
    expected = set(S05_FILE_MAP)
    if set(source) != expected:
        raise DualRunProjectionError("S05 collection names are not exact")
    id_fields = {
        "source_artifacts": "artifact_id",
        "aviation_extractions": "extraction_id",
        "model_field_provenance": "field_id",
        "provisional_signals": "signal_id",
        "processing_receipts": "receipt_id",
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for name in S05_FILE_MAP:
        records = [require_mapping(item, f"S05 {name} record") for item in require_list(source[name], f"S05 {name}")]
        if name in id_fields:
            indexed = unique_index(records, id_fields[name], f"S05 {name} record")
            result[name] = [indexed[key] for key in sorted(indexed)]
        else:
            indexed = unique_index(records, "source_artifact_id", f"S05 {name} disposition")
            result[name] = [indexed[key] for key in sorted(indexed)]
    reject_secret_or_unsafe_paths(result, path="S05_collections")
    return result


def _verify_s05_package(
    campaign: Mapping[str, Any],
    envelope: Mapping[str, Any],
    collections: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    manifest = require_mapping(envelope, "S05 package manifest")
    canonical_collections = _canonicalize_s05_collections(collections)
    if manifest.get("schema_version") != "skywatcher_producer_package.v2":
        raise DualRunProjectionError("unsupported S05 package schema")
    if manifest.get("producer_revision") != campaign.get("skywatcher_revision"):
        raise DualRunProjectionError("S05 producer revision drift")
    expected_sources = sorted(
        str(item["artifact_id"])
        for item in require_list(campaign.get("source_artifacts"), "campaign source artifacts")
    )
    if manifest.get("source_artifact_ids") != expected_sources:
        raise DualRunProjectionError("S05 source artifact set does not match campaign")
    source_ids = sorted(str(item["artifact_id"]) for item in canonical_collections["source_artifacts"])
    if source_ids != expected_sources:
        raise DualRunProjectionError("S05 source collection does not match campaign")
    accounting = require_mapping(manifest.get("accounting"), "S05 accounting")
    if int(accounting.get("inputs", -1)) != len(expected_sources):
        raise DualRunProjectionError("S05 input accounting does not match campaign")
    if int(accounting.get("inputs", -1)) != int(accounting.get("outputs", -2)) + int(accounting.get("excluded", -3)) + int(accounting.get("failed", -4)):
        raise DualRunProjectionError("S05 input accounting is incomplete")
    digest_payload = {
        "schema_version": "skywatcher_producer_package.v2",
        "producer_revision": manifest["producer_revision"],
        "collections": canonical_collections,
        "accounting": accounting,
    }
    expected_digest = sha256_json(digest_payload)
    if manifest.get("normalized_digest") != expected_digest:
        raise DualRunProjectionError("S05 normalized package digest mismatch")
    if manifest.get("certified") not in {None, False}:
        raise DualRunProjectionError("S05 package cannot be certified")
    return manifest, canonical_collections


def project_s05_deterministic_outputs(
    envelope: Mapping[str, Any], collections: Mapping[str, Any]
) -> list[dict[str, str]]:
    """Project exact canonical SHA-256 values for all eight S05 package files."""
    manifest = require_mapping(envelope, "S05 package manifest")
    source = require_mapping(collections, "S05 collections")
    outputs = [
        {
            "output_id": "manifest.json",
            "normalized_sha256": sha256_bytes(canonical_json_bytes(manifest)),
        }
    ]
    for name, filename in sorted(S05_FILE_MAP.items(), key=lambda item: item[1]):
        outputs.append(
            {
                "output_id": filename,
                "normalized_sha256": sha256_bytes(canonical_json_bytes(source[name])),
            }
        )
    return sorted(outputs, key=lambda item: item["output_id"])


def project_s05_model_fields(
    *,
    campaign: Mapping[str, Any],
    collections: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project model fields while preserving S05 field-level provenance exactly."""
    source_index = unique_index(
        require_list(campaign.get("source_artifacts"), "campaign source artifacts"),
        "artifact_id",
        "campaign source artifact",
    )
    provenance_index = unique_index(
        require_list(collections.get("model_field_provenance"), "S05 field provenance"),
        "field_id",
        "S05 field provenance",
    )
    fields: dict[str, dict[str, Any]] = {}
    for extraction in require_list(collections.get("aviation_extractions"), "S05 extractions"):
        extraction_record = require_mapping(extraction, "S05 extraction")
        source_id = str(extraction_record.get("source_artifact_id") or "")
        if source_id not in source_index:
            raise DualRunProjectionError("S05 extraction source is outside campaign")
        for raw_field in require_list(extraction_record.get("fields"), "S05 extraction fields"):
            field = require_mapping(raw_field, "S05 extraction field")
            provenance_id = str(field.get("provenance_id") or "")
            if provenance_id not in provenance_index:
                raise DualRunProjectionError("S05 extraction references missing field provenance")
            provenance_record = provenance_index[provenance_id]
            field_key = str(provenance_record.get("field_key") or "")
            if not field_key:
                raise DualRunProjectionError("S05 field provenance must preserve field_key")
            if field_key in fields:
                raise DualRunProjectionError("duplicate projected S05 field_key")
            if provenance_record.get("source_artifact_id") != source_id:
                raise DualRunProjectionError("S05 field provenance source mismatch")
            model_run_receipt_id = str(
                provenance_record.get("model_run_receipt_id") or ""
            )
            if not model_run_receipt_id:
                raise DualRunProjectionError(
                    "S05 field provenance requires model_run_receipt_id"
                )
            if model_run_receipt_id != str(
                extraction_record.get("model_run_receipt_id") or ""
            ):
                raise DualRunProjectionError(
                    "S05 field model-run receipt binding mismatch"
                )
            provenance = validate_provenance(
                {
                    key: provenance_record.get(key)
                    for key in (
                        "source_artifact_id",
                        "source_sha256",
                        "provider_id",
                        "model_id",
                        "model_revision",
                        "prompt_template_hash",
                        "policy_version",
                        "access_context_hash",
                        "extraction_schema_version",
                    )
                },
                campaign=campaign,
                source_index=source_index,
            )
            review_status = provenance_record.get("review_status")
            if review_status not in {"REVIEWED", "UNRESOLVED_REVIEW"}:
                raise DualRunProjectionError("S05 provenance review_status is required")
            fields[field_key] = {
                "field_key": field_key,
                "value": field.get("value"),
                "provenance": provenance,
                "review_status": review_status,
            }
    required = {
        str(value)
        for value in require_list(
            campaign.get("required_model_fields"), "campaign required model fields"
        )
    }
    if set(fields) != required:
        raise DualRunProjectionError("S05 projected model field set is not exact")
    return [fields[key] for key in sorted(fields)]


def build_candidate_lane_projection_input(
    *,
    campaign: Mapping[str, Any],
    trial_id: str,
    s05_envelope: Mapping[str, Any],
    s05_collections: Mapping[str, Any],
    execution_receipt: Mapping[str, Any],
    h06_job_record_id: str,
    h07_admission_receipt_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Project a verified S05 package into the H08 candidate-lane shape."""
    campaign_record = validate_campaign(campaign, trial_id)
    _validate_exact_required_outputs(campaign_record)
    if not h06_job_record_id or not h07_admission_receipt_id:
        raise DualRunProjectionError("candidate projection requires H06 and H07 references")
    receipt = validate_execution_receipt_ref(execution_receipt)
    manifest, collections = _verify_s05_package(
        campaign_record, s05_envelope, s05_collections
    )
    outputs = project_s05_deterministic_outputs(manifest, collections)
    if {item["output_id"] for item in outputs} != S05_OUTPUT_IDS:
        raise DualRunProjectionError("candidate deterministic output set is not exact")
    fields = project_s05_model_fields(campaign=campaign_record, collections=collections)
    accounting = require_mapping(manifest["accounting"], "S05 accounting")
    payload: dict[str, Any] = {
        "schema_version": "dual_run_lane_evidence.v1",
        "lane_evidence_id": "",
        "campaign_id": campaign_record["campaign_id"],
        "trial_id": trial_id,
        "lane": "ADR0006_CANDIDATE",
        "execution_receipt": receipt,
        "source_set_sha256": campaign_record["source_set_sha256"],
        "pins_sha256": campaign_record["pins_sha256"],
        "producer_package_id": manifest["package_id"],
        "producer_package_sha256": manifest["normalized_digest"],
        "h06_job_record_id": h06_job_record_id,
        "h07_admission_receipt_id": h07_admission_receipt_id,
        "deterministic_outputs": outputs,
        "model_fields": fields,
        "schema_violations": 0,
        "missing_required_provenance": 0,
        "input_accounting": {
            "inputs": accounting["inputs"],
            "processed": accounting["outputs"],
            "excluded": accounting["excluded"],
            "failed": accounting["failed"],
        },
        "output_accounting": {
            "required": len(S05_OUTPUT_IDS),
            "produced": len(outputs),
            "failed": 0,
        },
        "certified_state_created": False,
        "active_snapshot_promoted": False,
        "answer_eligible": False,
        "created_at": created_at,
    }
    reject_secret_or_unsafe_paths(payload, path="candidate_lane_projection")
    payload["lane_evidence_id"] = compute_lane_evidence_id(payload)
    return payload


def _write_json(path: Path, value: Any) -> str:
    data = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256_bytes(data)


def write_dual_run_evidence_staging(
    *,
    root: Path,
    campaign: Mapping[str, Any],
    equivalence_policy: Mapping[str, Any],
    trial_id: str,
    legacy_execution_receipt: Mapping[str, Any],
    legacy_shadow_export: Mapping[str, Any],
    legacy_lane: Mapping[str, Any],
    candidate_execution_receipt: Mapping[str, Any],
    s05_envelope: Mapping[str, Any],
    s05_collections: Mapping[str, Any],
    candidate_lane: Mapping[str, Any],
) -> dict[str, str]:
    """Write one deterministic, non-executing trial evidence staging layout."""
    validate_campaign(campaign, trial_id)
    if root.exists() and any(root.iterdir()):
        raise DualRunProjectionError("staging root must be absent or empty")
    for name, record in {
        "campaign": campaign,
        "equivalence_policy": equivalence_policy,
        "legacy_execution_receipt": legacy_execution_receipt,
        "legacy_shadow_export": legacy_shadow_export,
        "legacy_lane": legacy_lane,
        "candidate_execution_receipt": candidate_execution_receipt,
        "candidate_manifest": s05_envelope,
        "candidate_collections": s05_collections,
        "candidate_lane": candidate_lane,
    }.items():
        reject_secret_or_unsafe_paths(record, path=name)
    canonical_legacy_shadow_export_bytes(legacy_shadow_export)
    if legacy_lane.get("lane_evidence_id") != compute_lane_evidence_id(legacy_lane):
        raise DualRunProjectionError("legacy lane evidence identity mismatch")
    if candidate_lane.get("lane_evidence_id") != compute_lane_evidence_id(candidate_lane):
        raise DualRunProjectionError("candidate lane evidence identity mismatch")

    paths: dict[str, Any] = {
        "campaign_manifest.json": campaign,
        "model_field_equivalence_policy.json": equivalence_policy,
        f"trials/{trial_id}/legacy_shadow/execution_receipt.json": legacy_execution_receipt,
        f"trials/{trial_id}/legacy_shadow/legacy_shadow_export.json": legacy_shadow_export,
        f"trials/{trial_id}/legacy_shadow/lane_evidence.json": legacy_lane,
        f"trials/{trial_id}/adr0006_candidate/execution_receipt.json": candidate_execution_receipt,
        f"trials/{trial_id}/adr0006_candidate/producer_package/manifest.json": s05_envelope,
        f"trials/{trial_id}/adr0006_candidate/lane_evidence.json": candidate_lane,
    }
    for name, filename in S05_FILE_MAP.items():
        paths[
            f"trials/{trial_id}/adr0006_candidate/producer_package/{filename}"
        ] = require_mapping(s05_collections, "S05 collections")[name]
    digests: dict[str, str] = {}
    for relative_path in sorted(paths):
        digests[relative_path] = _write_json(root / relative_path, paths[relative_path])
    sums = "".join(f"{digest}  {path}\n" for path, digest in sorted(digests.items()))
    (root / "SHA256SUMS").write_text(sums, encoding="utf-8")
    digests["SHA256SUMS"] = sha256_bytes(sums.encode("utf-8"))
    return digests


__all__ = [
    "DualRunProjectionError",
    "S05_FILE_MAP",
    "S05_OUTPUT_IDS",
    "build_candidate_lane_projection_input",
    "build_legacy_lane_projection_input",
    "compute_lane_evidence_id",
    "project_s05_deterministic_outputs",
    "project_s05_model_fields",
    "write_dual_run_evidence_staging",
]
