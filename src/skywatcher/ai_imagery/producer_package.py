"""Deterministic, offline Skywatcher producer-package v2 builder.

The builder packages already-created local artifacts. It performs no acquisition,
model execution, remote database calls, or certification. All source inputs must
be fully partitioned into output, exclusion, or failure dispositions.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


class ProducerPackageError(ValueError):
    """Raised when records cannot form a complete deterministic package."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _materialize(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(record) for record in records]


def _indexed(records: list[dict[str, Any]], id_field: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        value = str(record.get(id_field) or "").strip()
        if not value:
            raise ProducerPackageError(f"missing {id_field}")
        if value in indexed:
            raise ProducerPackageError(f"duplicate {id_field}: {value}")
        indexed[value] = record
    return indexed


def _sorted_records(records: list[dict[str, Any]], id_field: str) -> list[dict[str, Any]]:
    indexed = _indexed(records, id_field)
    return [indexed[key] for key in sorted(indexed)]


def _source_ids_from_outputs(
    extractions: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> set[str]:
    outputs: set[str] = set()
    for record in extractions:
        if record.get("provisional") is not True:
            raise ProducerPackageError("aviation extraction must remain provisional")
        source_id = str(record.get("source_artifact_id") or "").strip()
        if not source_id:
            raise ProducerPackageError("extraction missing source_artifact_id")
        outputs.add(source_id)
    for record in signals:
        if record.get("provisional") is not True:
            raise ProducerPackageError("SATIM signal must remain provisional")
        source_ids = record.get("source_artifact_ids")
        if not isinstance(source_ids, list) or not source_ids:
            raise ProducerPackageError("signal missing source_artifact_ids")
        outputs.update(str(value).strip() for value in source_ids if str(value).strip())
    return outputs


def _ledger_source_ids(entries: list[dict[str, Any]], name: str) -> set[str]:
    values: set[str] = set()
    for entry in entries:
        source_id = str(entry.get("source_artifact_id") or "").strip()
        reason = str(entry.get("reason") or "").strip()
        if not source_id or not reason:
            raise ProducerPackageError(f"{name} entries require source_artifact_id and reason")
        if source_id in values:
            raise ProducerPackageError(f"duplicate {name} disposition for {source_id}")
        values.add(source_id)
    return values


def _validate_field_provenance_links(
    extractions: list[dict[str, Any]],
    provenance: list[dict[str, Any]],
) -> None:
    provenance_ids = set(_indexed(provenance, "field_id"))
    referenced: set[str] = set()
    for extraction in extractions:
        fields = extraction.get("fields")
        if not isinstance(fields, list) or not fields:
            raise ProducerPackageError("extraction fields must be a non-empty list")
        for field in fields:
            provenance_id = str(field.get("provenance_id") or "").strip()
            if not provenance_id:
                raise ProducerPackageError("every extraction field requires provenance_id")
            referenced.add(provenance_id)
    missing = sorted(referenced - provenance_ids)
    if missing:
        raise ProducerPackageError(f"missing field provenance records: {missing}")


def build_package(
    *,
    producer_revision: str,
    created_at: str,
    source_artifacts: Iterable[Mapping[str, Any]],
    aviation_extractions: Iterable[Mapping[str, Any]],
    model_field_provenance: Iterable[Mapping[str, Any]],
    provisional_signals: Iterable[Mapping[str, Any]],
    processing_receipts: Iterable[Mapping[str, Any]],
    exclusions: Iterable[Mapping[str, Any]] = (),
    failures: Iterable[Mapping[str, Any]] = (),
    package_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Build the schema-conformant envelope and canonical package collections."""
    if len(producer_revision) != 40 or any(
        ch not in "0123456789abcdef" for ch in producer_revision
    ):
        raise ProducerPackageError("producer_revision must be a lowercase 40-character SHA")
    if not created_at.strip():
        raise ProducerPackageError("created_at is required")

    collections = {
        "source_artifacts": _materialize(source_artifacts),
        "aviation_extractions": _materialize(aviation_extractions),
        "model_field_provenance": _materialize(model_field_provenance),
        "provisional_signals": _materialize(provisional_signals),
        "processing_receipts": _materialize(processing_receipts),
        "exclusions": _materialize(exclusions),
        "failures": _materialize(failures),
    }
    id_fields = {
        "source_artifacts": "artifact_id",
        "aviation_extractions": "extraction_id",
        "model_field_provenance": "field_id",
        "provisional_signals": "signal_id",
        "processing_receipts": "receipt_id",
    }
    for name, id_field in id_fields.items():
        collections[name] = _sorted_records(collections[name], id_field)
    collections["exclusions"] = sorted(
        collections["exclusions"],
        key=lambda item: str(item.get("source_artifact_id", "")),
    )
    collections["failures"] = sorted(
        collections["failures"],
        key=lambda item: str(item.get("source_artifact_id", "")),
    )

    source_index = _indexed(collections["source_artifacts"], "artifact_id")
    source_ids = set(source_index)
    output_sources = _source_ids_from_outputs(
        collections["aviation_extractions"], collections["provisional_signals"]
    )
    excluded_sources = _ledger_source_ids(collections["exclusions"], "exclusion")
    failed_sources = _ledger_source_ids(collections["failures"], "failure")
    unknown = sorted((output_sources | excluded_sources | failed_sources) - source_ids)
    if unknown:
        raise ProducerPackageError(f"dispositions reference unknown inputs: {unknown}")
    overlaps = {
        "output/excluded": output_sources & excluded_sources,
        "output/failed": output_sources & failed_sources,
        "excluded/failed": excluded_sources & failed_sources,
    }
    conflicting = {key: sorted(value) for key, value in overlaps.items() if value}
    if conflicting:
        raise ProducerPackageError(f"input dispositions overlap: {conflicting}")
    unaccounted = sorted(source_ids - output_sources - excluded_sources - failed_sources)
    if unaccounted:
        raise ProducerPackageError(f"unaccounted source artifacts: {unaccounted}")

    _validate_field_provenance_links(
        collections["aviation_extractions"], collections["model_field_provenance"]
    )
    receipt_ids = set(_indexed(collections["processing_receipts"], "receipt_id"))
    for extraction in collections["aviation_extractions"]:
        receipt_id = str(extraction.get("model_run_receipt_id") or "").strip()
        if receipt_id not in receipt_ids:
            raise ProducerPackageError(
                f"extraction references missing processing receipt: {receipt_id or '<empty>'}"
            )

    accounting = {
        "inputs": len(source_ids),
        "excluded": len(excluded_sources),
        "failed": len(failed_sources),
        "outputs": len(output_sources),
    }
    digest_payload = {
        "schema_version": "skywatcher_producer_package.v2",
        "producer_revision": producer_revision,
        "collections": collections,
        "accounting": accounting,
    }
    digest = hashlib.sha256(canonical_json(digest_payload).encode("utf-8")).hexdigest()
    envelope = {
        "schema_version": "skywatcher_producer_package.v2",
        "package_id": package_id or f"skywatcher-package-{digest[:24]}",
        "producer_revision": producer_revision,
        "created_at": created_at,
        "source_artifact_ids": sorted(source_ids),
        "aviation_extraction_ids": [
            record["extraction_id"] for record in collections["aviation_extractions"]
        ],
        "model_field_provenance_ids": [
            record["field_id"] for record in collections["model_field_provenance"]
        ],
        "provisional_signal_ids": [
            record["signal_id"] for record in collections["provisional_signals"]
        ],
        "processing_receipt_ids": [
            record["receipt_id"] for record in collections["processing_receipts"]
        ],
        "accounting": accounting,
        "normalized_digest": digest,
        "certified": False,
    }
    return envelope, collections


def write_package(
    out_dir: Path,
    envelope: Mapping[str, Any],
    collections: Mapping[str, list[dict[str, Any]]],
) -> None:
    """Write canonical UTF-8 JSON with stable ordering and final newlines."""
    out_dir.mkdir(parents=True, exist_ok=True)
    file_map = {
        "source_artifacts": "source_artifacts.json",
        "aviation_extractions": "aviation_extractions.json",
        "model_field_provenance": "model_field_provenance.json",
        "provisional_signals": "provisional_signals.json",
        "processing_receipts": "processing_receipts.json",
        "exclusions": "exclusions.json",
        "failures": "failures.json",
    }
    for name, filename in file_map.items():
        (out_dir / filename).write_text(
            canonical_json(collections[name]) + "\n", encoding="utf-8"
        )
    (out_dir / "manifest.json").write_text(
        canonical_json(dict(envelope)) + "\n", encoding="utf-8"
    )
