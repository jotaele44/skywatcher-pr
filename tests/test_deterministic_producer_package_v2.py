from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from skywatcher.ai_imagery.producer_package import (
    ProducerPackageError,
    build_package,
    write_package,
)

SHA = "a" * 40


def _records() -> dict:
    return {
        "source_artifacts": [
            {"artifact_id": "artifact-b", "sha256": "b" * 64},
            {"artifact_id": "artifact-a", "sha256": "a" * 64},
            {"artifact_id": "artifact-c", "sha256": "c" * 64},
        ],
        "aviation_extractions": [
            {
                "schema_version": "aviation_vision_extraction.v1",
                "extraction_id": "extract-1",
                "source_artifact_id": "artifact-a",
                "model_run_receipt_id": "receipt-1",
                "extraction_schema_version": "v1",
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
                "schema_version": "model_field_provenance.v1",
                "field_id": "field-1",
                "source_artifact_id": "artifact-a",
                "model_run_receipt_id": "receipt-1",
                "provider": "provider-recorded-in-receipt",
                "model": "model-recorded-in-receipt",
            }
        ],
        "provisional_signals": [
            {
                "schema_version": "satim_provisional_signal.v1",
                "signal_id": "signal-1",
                "source_artifact_ids": ["artifact-b"],
                "provisional": True,
            }
        ],
        "processing_receipts": [
            {"receipt_id": "receipt-1", "outcome": "SUCCEEDED"}
        ],
        "exclusions": [
            {"source_artifact_id": "artifact-c", "reason": "unsupported_media"}
        ],
        "failures": [],
    }


def _build(records: dict):
    return build_package(
        producer_revision=SHA,
        created_at="2026-07-30T15:00:00Z",
        **records,
    )


def test_generated_envelope_conforms_to_committed_schema() -> None:
    envelope, _ = _build(_records())
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "schemas"
        / "ai_imagery"
        / "skywatcher_producer_package.v2.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(envelope)


def test_digest_is_reproducible_across_input_order() -> None:
    records = _records()
    first, first_collections = _build(records)
    shuffled = _records()
    shuffled["source_artifacts"].reverse()
    second, second_collections = _build(shuffled)
    assert first == second
    assert first_collections == second_collections
    assert first["package_id"].endswith(first["normalized_digest"][:24])
    assert first["certified"] is False


def test_complete_accounting_is_a_strict_partition() -> None:
    envelope, _ = _build(_records())
    assert envelope["accounting"] == {
        "inputs": 3,
        "excluded": 1,
        "failed": 0,
        "outputs": 2,
    }
    incomplete = _records()
    incomplete["exclusions"] = []
    with pytest.raises(ProducerPackageError, match="unaccounted"):
        _build(incomplete)
    overlapping = _records()
    overlapping["failures"] = [
        {"source_artifact_id": "artifact-b", "reason": "decode_error"}
    ]
    with pytest.raises(ProducerPackageError, match="overlap"):
        _build(overlapping)


def test_package_preserves_model_and_field_provenance_without_ocr_relabeling(
    tmp_path: Path,
) -> None:
    envelope, collections = _build(_records())
    write_package(tmp_path, envelope, collections)
    extraction = json.loads(
        (tmp_path / "aviation_extractions.json").read_text()
    )[0]
    assert extraction["model_run_receipt_id"] == "receipt-1"
    assert extraction["fields"][0]["provenance_id"] == "field-1"
    combined = "".join(path.read_text() for path in tmp_path.iterdir()).lower()
    assert "ensemble_ocr" not in combined
    assert "fr24_screenshot_ocr" not in combined


def test_package_bytes_are_reproducible(tmp_path: Path) -> None:
    envelope, collections = _build(_records())
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_package(first, envelope, collections)
    write_package(second, envelope, collections)
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }


def test_builder_contains_no_network_model_or_database_runtime() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "skywatcher"
        / "ai_imagery"
        / "producer_package.py"
    ).read_text().lower()
    for forbidden in (
        "import requests",
        "import urllib",
        "import socket",
        "anthropic",
        "openai",
        "sqlite3",
        "database_url",
    ):
        assert forbidden not in source
