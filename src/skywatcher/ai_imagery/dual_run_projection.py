"""Pure H08 lane projection and deterministic staging for ADR 0006 S06."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ._dual_run_common import (
    DualRunProjectionError,
    canonical_json_bytes,
    clean_relative_path,
    ensure_run_id,
    ensure_sha256,
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


def compute_lane_evidence_id(record: Mapping[str, Any]) -> str:
    payload = dict(record)
    payload.pop("lane_evidence_id", None)
    return "dual-run-lane-sha256-" + sha256_json(payload)


def _exact_outputs(campaign: Mapping[str, Any]) -> None:
    required = set(
        map(
            str,
            require_list(
                campaign.get("required_deterministic_outputs"),
                "campaign required deterministic outputs",
            ),
        )
    )
    if required != S05_OUTPUT_IDS:
        raise DualRunProjectionError("campaign deterministic output set is not exact")


def build_legacy_lane_projection_input(
    *,
    campaign: Mapping[str, Any],
    trial_id: str,
    legacy_shadow_export: Mapping[str, Any],
    execution_receipt: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    camp = validate_campaign(campaign, trial_id)
    _exact_outputs(camp)
    export = require_mapping(legacy_shadow_export, "legacy shadow export")
    if export.get("legacy_shadow_export_id") != compute_legacy_shadow_export_id(export):
        raise DualRunProjectionError("legacy shadow export identity mismatch")
    for key, expected, message in (
        ("campaign_id", camp["campaign_id"], "campaign binding mismatch"),
        ("trial_id", trial_id, "trial binding mismatch"),
        ("source_set_sha256", camp["source_set_sha256"], "source-set drift"),
        ("pins_sha256", camp["pins_sha256"], "pin-set drift"),
    ):
        if export.get(key) != expected:
            raise DualRunProjectionError(f"legacy export {message}")
    receipt = validate_execution_receipt_ref(execution_receipt)
    if require_mapping(export.get("execution_receipt"), "legacy export receipt") != {
        "run_id": receipt["run_id"],
        "receipt_sha256": receipt["receipt_sha256"],
    }:
        raise DualRunProjectionError("legacy export execution-receipt binding mismatch")
    fields = []
    for raw in require_list(export.get("model_fields"), "legacy model fields"):
        field = require_mapping(raw, "legacy model field")
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
    payload = {
        "schema_version": "dual_run_lane_evidence.v1",
        "lane_evidence_id": "",
        "campaign_id": camp["campaign_id"],
        "trial_id": trial_id,
        "lane": "LEGACY_SHADOW",
        "execution_receipt": receipt,
        "source_set_sha256": camp["source_set_sha256"],
        "pins_sha256": camp["pins_sha256"],
        "legacy_shadow_export_id": export["legacy_shadow_export_id"],
        "deterministic_outputs": require_list(
            export.get("deterministic_outputs"), "legacy deterministic outputs"
        ),
        "model_fields": fields,
        "schema_violations": 0,
        "missing_required_provenance": 0,
        "input_accounting": require_mapping(
            export.get("input_accounting"), "legacy input accounting"
        ),
        "output_accounting": require_mapping(
            export.get("output_accounting"), "legacy output accounting"
        ),
        "certified_state_created": False,
        "active_snapshot_promoted": False,
        "answer_eligible": False,
        "created_at": created_at,
    }
    reject_secret_or_unsafe_paths(payload, path="legacy_lane_projection")
    payload["lane_evidence_id"] = compute_lane_evidence_id(payload)
    return payload


def _canonicalize_s05_collections(
    collections: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    source = require_mapping(collections, "S05 collections")
    if set(source) != set(S05_FILE_MAP):
        raise DualRunProjectionError("S05 collection names are not exact")
    ids = {
        "source_artifacts": "artifact_id",
        "aviation_extractions": "extraction_id",
        "model_field_provenance": "field_id",
        "provisional_signals": "signal_id",
        "processing_receipts": "receipt_id",
    }
    result = {}
    for name in S05_FILE_MAP:
        records = [
            require_mapping(item, f"S05 {name} record")
            for item in require_list(source[name], f"S05 {name}")
        ]
        key = ids.get(name, "source_artifact_id")
        index = unique_index(records, key, f"S05 {name} record")
        result[name] = [index[value] for value in sorted(index)]
    reject_secret_or_unsafe_paths(result, path="S05_collections")
    return result


def _verify_s05_package(
    campaign: Mapping[str, Any],
    envelope: Mapping[str, Any],
    collections: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    manifest = require_mapping(envelope, "S05 package manifest")
    canonical = _canonicalize_s05_collections(collections)
    if manifest.get("schema_version") != "skywatcher_producer_package.v2":
        raise DualRunProjectionError("unsupported S05 package schema")
    if manifest.get("producer_revision") != campaign.get("skywatcher_revision"):
        raise DualRunProjectionError("S05 producer revision drift")
    expected = sorted(
        str(item["artifact_id"])
        for item in require_list(campaign.get("source_artifacts"), "campaign sources")
    )
    if manifest.get("source_artifact_ids") != expected:
        raise DualRunProjectionError("S05 source artifact set does not match campaign")
    if sorted(str(item["artifact_id"]) for item in canonical["source_artifacts"]) != expected:
        raise DualRunProjectionError("S05 source collection does not match campaign")
    accounting = require_mapping(manifest.get("accounting"), "S05 accounting")
    inputs = int(accounting.get("inputs", -1))
    terminal = sum(int(accounting.get(key, -2)) for key in ("outputs", "excluded", "failed"))
    if inputs != len(expected):
        raise DualRunProjectionError("S05 input accounting does not match campaign")
    if inputs != terminal:
        raise DualRunProjectionError("S05 input accounting is incomplete")
    digest = sha256_json(
        {
            "schema_version": "skywatcher_producer_package.v2",
            "producer_revision": manifest["producer_revision"],
            "collections": canonical,
            "accounting": accounting,
        }
    )
    if manifest.get("normalized_digest") != digest:
        raise DualRunProjectionError("S05 normalized package digest mismatch")
    if manifest.get("certified") not in {None, False}:
        raise DualRunProjectionError("S05 package cannot be certified")
    return manifest, canonical


def project_s05_deterministic_outputs(
    envelope: Mapping[str, Any], collections: Mapping[str, Any]
) -> list[dict[str, str]]:
    manifest = require_mapping(envelope, "S05 package manifest")
    source = require_mapping(collections, "S05 collections")
    outputs = [
        {
            "output_id": "manifest.json",
            "normalized_sha256": sha256_bytes(canonical_json_bytes(manifest)),
        }
    ]
    outputs.extend(
        {
            "output_id": filename,
            "normalized_sha256": sha256_bytes(canonical_json_bytes(source[name])),
        }
        for name, filename in S05_FILE_MAP.items()
    )
    return sorted(outputs, key=lambda item: item["output_id"])


def project_s05_model_fields(
    *, campaign: Mapping[str, Any], collections: Mapping[str, Any]
) -> list[dict[str, Any]]:
    sources = unique_index(
        require_list(campaign.get("source_artifacts"), "campaign sources"),
        "artifact_id",
        "campaign source",
    )
    provenance = unique_index(
        require_list(collections.get("model_field_provenance"), "S05 provenance"),
        "field_id",
        "S05 provenance",
    )
    fields = {}
    for raw_extraction in require_list(collections.get("aviation_extractions"), "S05 extractions"):
        extraction = require_mapping(raw_extraction, "S05 extraction")
        source_id = str(extraction.get("source_artifact_id") or "")
        if source_id not in sources:
            raise DualRunProjectionError("S05 extraction source is outside campaign")
        for raw_field in require_list(extraction.get("fields"), "S05 fields"):
            field = require_mapping(raw_field, "S05 field")
            provenance_id = str(field.get("provenance_id") or "")
            if provenance_id not in provenance:
                raise DualRunProjectionError("S05 extraction references missing provenance")
            record = provenance[provenance_id]
            field_key = str(record.get("field_key") or "")
            if not field_key or field_key in fields:
                raise DualRunProjectionError("S05 projected field_key is missing or duplicate")
            if record.get("source_artifact_id") != source_id:
                raise DualRunProjectionError("S05 field provenance source mismatch")
            receipt_id = str(record.get("model_run_receipt_id") or "")
            if not receipt_id or receipt_id != str(extraction.get("model_run_receipt_id") or ""):
                raise DualRunProjectionError(
                    "S05 field provenance model-run receipt binding mismatch"
                )
            model_provenance = validate_provenance(
                {
                    key: record.get(key)
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
                source_index=sources,
            )
            review_status = record.get("review_status")
            if review_status not in {"REVIEWED", "UNRESOLVED_REVIEW"}:
                raise DualRunProjectionError("S05 provenance review_status is required")
            fields[field_key] = {
                "field_key": field_key,
                "value": field.get("value"),
                "provenance": model_provenance,
                "review_status": review_status,
            }
    required = set(map(str, require_list(campaign.get("required_model_fields"), "required fields")))
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
    camp = validate_campaign(campaign, trial_id)
    _exact_outputs(camp)
    if not h06_job_record_id or not h07_admission_receipt_id:
        raise DualRunProjectionError("candidate projection requires H06 and H07 references")
    receipt = validate_execution_receipt_ref(execution_receipt)
    manifest, collections = _verify_s05_package(camp, s05_envelope, s05_collections)
    outputs = project_s05_deterministic_outputs(manifest, collections)
    fields = project_s05_model_fields(campaign=camp, collections=collections)
    accounting = require_mapping(manifest["accounting"], "S05 accounting")
    payload = {
        "schema_version": "dual_run_lane_evidence.v1",
        "lane_evidence_id": "",
        "campaign_id": camp["campaign_id"],
        "trial_id": trial_id,
        "lane": "ADR0006_CANDIDATE",
        "execution_receipt": receipt,
        "source_set_sha256": camp["source_set_sha256"],
        "pins_sha256": camp["pins_sha256"],
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
        "output_accounting": {"required": 8, "produced": len(outputs), "failed": 0},
        "certified_state_created": False,
        "active_snapshot_promoted": False,
        "answer_eligible": False,
        "created_at": created_at,
    }
    reject_secret_or_unsafe_paths(payload, path="candidate_lane_projection")
    payload["lane_evidence_id"] = compute_lane_evidence_id(payload)
    return payload


def _validate_policy(campaign: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    record = require_mapping(policy, "equivalence policy")
    payload = dict(record)
    payload.pop("policy_id", None)
    expected = "model-equivalence-policy-sha256-" + sha256_json(payload)
    pins = require_mapping(campaign.get("pins"), "campaign pins")
    if record.get("policy_id") != expected:
        raise DualRunProjectionError("equivalence policy identity mismatch")
    if pins.get("equivalence_policy_id") != expected:
        raise DualRunProjectionError("equivalence policy ID does not match campaign pin")
    if pins.get("equivalence_policy_sha256") != expected.rsplit("-", 1)[-1]:
        raise DualRunProjectionError("equivalence policy SHA-256 does not match campaign pin")
    return record


def _validate_receipt(
    document: Mapping[str, Any], reference: Mapping[str, Any], label: str
) -> dict[str, Any]:
    record = require_mapping(document, label)
    if set(record) != {"receipt", "signature"}:
        raise DualRunProjectionError(f"{label} envelope fields are not exact")
    body = require_mapping(record.get("receipt"), f"{label} body")
    signature = require_mapping(record.get("signature"), f"{label} signature")
    if set(signature) != {"key_id", "algorithm", "value", "payload_sha256"}:
        raise DualRunProjectionError(f"{label} signature material is incomplete")
    compact = validate_execution_receipt_ref(reference)
    if ensure_run_id(body.get("run_id")) != compact["run_id"]:
        raise DualRunProjectionError(f"{label} run_id does not match compact reference")
    if not str(signature.get("key_id") or "") or not str(signature.get("value") or ""):
        raise DualRunProjectionError(f"{label} signature material is incomplete")
    if signature.get("algorithm") != "Ed25519":
        raise DualRunProjectionError(f"{label} signature algorithm must be Ed25519")
    digest = sha256_json(body)
    if ensure_sha256(signature.get("payload_sha256"), f"{label} digest") != digest:
        raise DualRunProjectionError(f"{label} SHA-256 does not match signature block")
    if compact["receipt_sha256"] != digest:
        raise DualRunProjectionError(f"{label} SHA-256 does not match compact reference")
    return record


def _target(root: Path, relative: str) -> Path:
    path = (root.resolve(strict=False) / clean_relative_path(relative, "staging path")).resolve(
        strict=False
    )
    try:
        path.relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise DualRunProjectionError("staging path escapes resolved package root") from exc
    return path


def _write(path: Path, value: Any) -> str:
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
    root = Path(root)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise DualRunProjectionError("staging root must be absent or empty directory")
    camp = validate_campaign(campaign, trial_id)
    policy = _validate_policy(camp, equivalence_policy)
    export = require_mapping(legacy_shadow_export, "legacy shadow export")
    legacy = require_mapping(legacy_lane, "legacy lane")
    candidate = require_mapping(candidate_lane, "candidate lane")
    manifest, collections = _verify_s05_package(camp, s05_envelope, s05_collections)
    for name, record in {
        "campaign": camp,
        "policy": policy,
        "legacy_receipt": legacy_execution_receipt,
        "legacy_export": export,
        "legacy_lane": legacy,
        "candidate_receipt": candidate_execution_receipt,
        "candidate_manifest": manifest,
        "candidate_collections": collections,
        "candidate_lane": candidate,
    }.items():
        reject_secret_or_unsafe_paths(record, path=name)
    canonical_legacy_shadow_export_bytes(export)
    expected_legacy = build_legacy_lane_projection_input(
        campaign=camp,
        trial_id=trial_id,
        legacy_shadow_export=export,
        execution_receipt=require_mapping(legacy.get("execution_receipt"), "legacy receipt"),
        created_at=str(legacy.get("created_at") or ""),
    )
    if legacy != expected_legacy:
        raise DualRunProjectionError("legacy lane is not bound to staged campaign and export")
    expected_candidate = build_candidate_lane_projection_input(
        campaign=camp,
        trial_id=trial_id,
        s05_envelope=manifest,
        s05_collections=collections,
        execution_receipt=require_mapping(candidate.get("execution_receipt"), "candidate receipt"),
        h06_job_record_id=str(candidate.get("h06_job_record_id") or ""),
        h07_admission_receipt_id=str(candidate.get("h07_admission_receipt_id") or ""),
        created_at=str(candidate.get("created_at") or ""),
    )
    if candidate != expected_candidate:
        raise DualRunProjectionError("candidate lane is not bound to staged campaign and package")
    _validate_receipt(legacy_execution_receipt, legacy["execution_receipt"], "legacy receipt")
    _validate_receipt(
        candidate_execution_receipt, candidate["execution_receipt"], "candidate receipt"
    )
    prefix = f"trials/{trial_id}"
    paths = {
        "campaign_manifest.json": camp,
        "model_field_equivalence_policy.json": policy,
        f"{prefix}/legacy_shadow/execution_receipt.json": legacy_execution_receipt,
        f"{prefix}/legacy_shadow/legacy_shadow_export.json": export,
        f"{prefix}/legacy_shadow/lane_evidence.json": legacy,
        f"{prefix}/adr0006_candidate/execution_receipt.json": candidate_execution_receipt,
        f"{prefix}/adr0006_candidate/producer_package/manifest.json": manifest,
        f"{prefix}/adr0006_candidate/lane_evidence.json": candidate,
    }
    for name, filename in S05_FILE_MAP.items():
        paths[f"{prefix}/adr0006_candidate/producer_package/{filename}"] = collections[name]
    targets = {relative: _target(root, relative) for relative in paths}
    sums_path = _target(root, "SHA256SUMS")
    digests = {relative: _write(targets[relative], paths[relative]) for relative in sorted(paths)}
    sums = "".join(f"{digest}  {path}\n" for path, digest in sorted(digests.items()))
    sums_path.parent.mkdir(parents=True, exist_ok=True)
    sums_path.write_text(sums, encoding="utf-8")
    digests["SHA256SUMS"] = sha256_bytes(sums.encode())
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
