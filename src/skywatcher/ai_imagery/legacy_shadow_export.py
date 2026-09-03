"""Pure legacy-shadow normalization and export construction for ADR 0006 S06."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ._dual_run_common import (
    DualRunProjectionError,
    canonical_json_bytes,
    ensure_revision,
    ensure_sha256,
    reject_secret_or_unsafe_paths,
    require_list,
    require_mapping,
    sha256_json,
    unique_index,
    validate_campaign,
    validate_execution_receipt_ref,
    validate_provenance,
)


def _normalize_mapping_records(
    records: Iterable[Mapping[str, Any]], *, identity_field: str, label: str
) -> list[dict[str, Any]]:
    indexed = unique_index(records, identity_field, label)
    normalized: list[dict[str, Any]] = []
    for identity in sorted(indexed):
        record = indexed[identity]
        reject_secret_or_unsafe_paths(record, path=f"{label}.{identity}")
        normalized.append(record)
    return normalized


def normalize_legacy_csv_checkpoint_and_logs(
    *,
    csv_rows: Iterable[Mapping[str, Any]],
    checkpoint_entries: Iterable[Mapping[str, Any]],
    log_records: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Normalize already-read legacy records without executing or relabeling them."""
    return {
        "csv_rows": _normalize_mapping_records(
            csv_rows, identity_field="id", label="legacy CSV row"
        ),
        "checkpoint_entries": _normalize_mapping_records(
            checkpoint_entries,
            identity_field="source_artifact_id",
            label="legacy checkpoint entry",
        ),
        "log_records": _normalize_mapping_records(
            log_records, identity_field="log_id", label="legacy log record"
        ),
    }


def _validate_source_artifacts(
    campaign: Mapping[str, Any], records: Iterable[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    supplied = unique_index(records, "artifact_id", "legacy source artifact")
    expected = unique_index(
        require_list(campaign.get("source_artifacts"), "campaign source artifacts"),
        "artifact_id",
        "campaign source artifact",
    )
    if set(supplied) != set(expected):
        raise DualRunProjectionError("legacy source artifact set does not match campaign")
    for artifact_id in supplied:
        if supplied[artifact_id] != expected[artifact_id]:
            raise DualRunProjectionError("legacy source artifact metadata drift")
    return [supplied[key] for key in sorted(supplied)], supplied


def _validate_dispositions(
    source_index: Mapping[str, Mapping[str, Any]],
    dispositions: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    indexed = unique_index(dispositions, "source_artifact_id", "legacy disposition")
    if set(indexed) != set(source_index):
        raise DualRunProjectionError("legacy dispositions must cover the exact source set")
    counts = {"PROCESSED": 0, "EXCLUDED": 0, "FAILED": 0}
    normalized: list[dict[str, Any]] = []
    for source_id in sorted(indexed):
        record = indexed[source_id]
        if set(record) != {"source_artifact_id", "status", "reason"}:
            raise DualRunProjectionError("legacy disposition fields are not exact")
        status = str(record["status"])
        if status not in counts:
            raise DualRunProjectionError("unsupported legacy disposition status")
        if not str(record["reason"]):
            raise DualRunProjectionError("legacy disposition reason is required")
        counts[status] += 1
        normalized.append(record)
    if len(source_index) != sum(counts.values()):
        raise DualRunProjectionError("legacy input accounting is incomplete")
    return normalized, counts


def _validate_deterministic_outputs(
    campaign: Mapping[str, Any], records: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    indexed = unique_index(records, "output_id", "legacy deterministic output")
    required = {
        str(value)
        for value in require_list(
            campaign.get("required_deterministic_outputs"),
            "campaign required deterministic outputs",
        )
    }
    if set(indexed) != required:
        raise DualRunProjectionError("legacy deterministic output set is not exact")
    normalized: list[dict[str, Any]] = []
    for output_id in sorted(indexed):
        record = indexed[output_id]
        if set(record) != {"output_id", "normalized_sha256"}:
            raise DualRunProjectionError("legacy deterministic output fields are not exact")
        ensure_sha256(record["normalized_sha256"], "legacy normalized output sha256")
        normalized.append(record)
    return normalized


def _validate_extended_model_provenance(
    provenance: Mapping[str, Any],
    *,
    campaign: Mapping[str, Any],
    source_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    record = require_mapping(provenance, "legacy model field provenance")
    h08_keys = {
        "source_artifact_id",
        "source_sha256",
        "provider_id",
        "model_id",
        "model_revision",
        "prompt_template_hash",
        "policy_version",
        "access_context_hash",
        "extraction_schema_version",
    }
    required = h08_keys | {"model_run_receipt_id"}
    if set(record) != required:
        missing = sorted(required - set(record))
        extra = sorted(set(record) - required)
        raise DualRunProjectionError(
            f"legacy model provenance must be exact; missing={missing}, extra={extra}"
        )
    if not str(record["model_run_receipt_id"]):
        raise DualRunProjectionError("legacy model_run_receipt_id is required")
    validate_provenance(
        {key: record[key] for key in h08_keys},
        campaign=campaign,
        source_index=source_index,
    )
    return record


def _validate_model_fields(
    campaign: Mapping[str, Any],
    source_index: Mapping[str, Mapping[str, Any]],
    records: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    indexed = unique_index(records, "field_key", "legacy model field")
    required = {
        str(value)
        for value in require_list(
            campaign.get("required_model_fields"), "campaign required model fields"
        )
    }
    if set(indexed) != required:
        raise DualRunProjectionError(
            "historical legacy output lacks the exact required field/provenance set"
        )
    normalized: list[dict[str, Any]] = []
    for field_key in sorted(indexed):
        record = indexed[field_key]
        if set(record) != {"field_key", "value", "provenance", "review_status"}:
            raise DualRunProjectionError("legacy model field structure is not exact")
        if record["review_status"] not in {"REVIEWED", "UNRESOLVED_REVIEW"}:
            raise DualRunProjectionError("legacy model field review status is unsupported")
        provenance = _validate_extended_model_provenance(
            require_mapping(record["provenance"], "legacy model provenance"),
            campaign=campaign,
            source_index=source_index,
        )
        normalized.append(
            {
                "field_key": field_key,
                "value": record["value"],
                "provenance": provenance,
                "review_status": record["review_status"],
            }
        )
    return normalized


def legacy_shadow_export_identity_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    payload.pop("legacy_shadow_export_id", None)
    return payload


def compute_legacy_shadow_export_id(record: Mapping[str, Any]) -> str:
    return "legacy-shadow-export-sha256-" + sha256_json(
        legacy_shadow_export_identity_payload(record)
    )


def build_legacy_shadow_export(
    *,
    campaign: Mapping[str, Any],
    trial_id: str,
    created_at: str,
    execution_receipt: Mapping[str, Any],
    engine: Mapping[str, Any],
    normalized_legacy_records: Mapping[str, Any],
    source_artifacts: Iterable[Mapping[str, Any]],
    dispositions: Iterable[Mapping[str, Any]],
    deterministic_outputs: Iterable[Mapping[str, Any]],
    model_fields: Iterable[Mapping[str, Any]],
    historical_artifacts: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build one content-addressed, non-authoritative legacy shadow export."""
    campaign_record = validate_campaign(campaign, trial_id)
    receipt = validate_execution_receipt_ref(execution_receipt)
    engine_record = require_mapping(engine, "legacy engine")
    if set(engine_record) != {"engine_id", "engine_revision"}:
        raise DualRunProjectionError("legacy engine fields are not exact")
    if not str(engine_record["engine_id"]):
        raise DualRunProjectionError("legacy engine_id is required")
    ensure_revision(engine_record["engine_revision"], "legacy engine revision")

    normalized_records = require_mapping(
        normalized_legacy_records, "normalized legacy records"
    )
    if set(normalized_records) != {"csv_rows", "checkpoint_entries", "log_records"}:
        raise DualRunProjectionError("normalized legacy record groups are not exact")
    for key in normalized_records:
        require_list(normalized_records[key], f"normalized legacy {key}")
    reject_secret_or_unsafe_paths(normalized_records, path="normalized_legacy_records")

    sources, source_index = _validate_source_artifacts(campaign_record, source_artifacts)
    normalized_dispositions, disposition_counts = _validate_dispositions(
        source_index, dispositions
    )
    outputs = _validate_deterministic_outputs(campaign_record, deterministic_outputs)
    fields = _validate_model_fields(campaign_record, source_index, model_fields)

    history = _normalize_mapping_records(
        historical_artifacts,
        identity_field="logical_name",
        label="legacy historical artifact",
    )
    for record in history:
        required_history = {"logical_name", "sha256", "bytes", "media_type", "relative_path"}
        if set(record) != required_history:
            raise DualRunProjectionError("historical artifact fields are not exact")
        ensure_sha256(record["sha256"], "historical artifact sha256")
        if not isinstance(record["bytes"], int) or record["bytes"] < 0:
            raise DualRunProjectionError("historical artifact bytes must be non-negative")

    payload: dict[str, Any] = {
        "schema_version": "legacy_shadow_export.v1",
        "legacy_shadow_export_id": "",
        "campaign_id": campaign_record["campaign_id"],
        "trial_id": trial_id,
        "skywatcher_revision": campaign_record["skywatcher_revision"],
        "source_set_sha256": campaign_record["source_set_sha256"],
        "pins_sha256": campaign_record["pins_sha256"],
        "engine": engine_record,
        "execution_receipt": {
            "run_id": receipt["run_id"],
            "receipt_sha256": receipt["receipt_sha256"],
        },
        "source_artifacts": sources,
        "normalized_legacy_records": normalized_records,
        "dispositions": normalized_dispositions,
        "deterministic_outputs": outputs,
        "model_fields": fields,
        "historical_artifacts": history,
        "input_accounting": {
            "inputs": len(sources),
            "processed": disposition_counts["PROCESSED"],
            "excluded": disposition_counts["EXCLUDED"],
            "failed": disposition_counts["FAILED"],
        },
        "output_accounting": {
            "required": len(outputs),
            "produced": len(outputs),
            "failed": 0,
        },
        "production_mutation_allowed": False,
        "certified_state_created": False,
        "active_snapshot_promoted": False,
        "retirement_authorized": False,
        "created_at": created_at,
    }
    reject_secret_or_unsafe_paths(payload, path="legacy_shadow_export")
    payload["legacy_shadow_export_id"] = compute_legacy_shadow_export_id(payload)
    return payload


def canonical_legacy_shadow_export_bytes(record: Mapping[str, Any]) -> bytes:
    expected = compute_legacy_shadow_export_id(record)
    if record.get("legacy_shadow_export_id") != expected:
        raise DualRunProjectionError("legacy shadow export identity mismatch")
    return canonical_json_bytes(record)


__all__ = [
    "DualRunProjectionError",
    "build_legacy_shadow_export",
    "canonical_legacy_shadow_export_bytes",
    "compute_legacy_shadow_export_id",
    "normalize_legacy_csv_checkpoint_and_logs",
]
