"""Stdlib-only contract tests for ADR 0006 Skywatcher domain schemas."""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "ai_imagery"


def _load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def test_schema_documents_are_draft_2020_12_objects() -> None:
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False


def test_aviation_extraction_is_provider_neutral_and_provisional() -> None:
    schema = _load("aviation_vision_extraction.v1.schema.json")
    required = set(schema["required"])
    assert {"source_artifact_id", "model_run_receipt_id", "fields", "review_status", "provisional"} <= required
    assert schema["properties"]["provisional"]["const"] is True
    serialized = json.dumps(schema)
    assert "ANTHROPIC_API_KEY" not in serialized
    assert "claude-haiku" not in serialized.lower()
    assert "openai" not in serialized.lower()


def test_each_aviation_field_requires_provenance_reference() -> None:
    schema = _load("aviation_vision_extraction.v1.schema.json")
    field_schema = schema["properties"]["fields"]["items"]
    assert "provenance_id" in field_schema["required"]
    assert "validation_outcome" in field_schema["required"]


def test_package_contract_is_artifact_only_and_deterministic() -> None:
    schema = _load("skywatcher_producer_package.v2.schema.json")
    required = set(schema["required"])
    assert {"source_artifact_ids", "model_field_provenance_ids", "processing_receipt_ids", "accounting", "normalized_digest"} <= required
    assert schema["properties"]["normalized_digest"]["pattern"] == "^[0-9a-f]{64}$"
    assert schema["properties"]["certified"]["const"] is False
    serialized = json.dumps(schema).lower()
    assert "database_url" not in serialized
    assert "rpc" not in serialized
    assert "provider_key" not in serialized


def test_package_requires_complete_accounting_dimensions() -> None:
    schema = _load("skywatcher_producer_package.v2.schema.json")
    accounting = schema["properties"]["accounting"]
    assert set(accounting["required"]) == {"inputs", "excluded", "failed", "outputs"}
