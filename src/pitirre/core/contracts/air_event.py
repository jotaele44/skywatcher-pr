"""Contract helpers for PITIRRE AIR event v2."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

AIR_EVENT_SCHEMA_VERSION = "2.0"
AIR_EVENT_SCHEMA_RELATIVE_PATH = Path("schemas/air_event_v2.schema.json")


def repository_root() -> Path:
    """Return the repository root for an in-tree checkout."""
    return Path(__file__).resolve().parents[4]


def load_air_event_schema(*, root: Path | None = None) -> dict[str, Any]:
    """Load the immutable AIR event v2 JSON Schema."""
    base = repository_root() if root is None else root
    payload = json.loads(
        (base / AIR_EVENT_SCHEMA_RELATIVE_PATH).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(payload)
    return payload


def validate_air_event_contract(
    event: Mapping[str, Any],
    *,
    root: Path | None = None,
) -> None:
    """Fail closed if an AIR event violates the versioned v2 contract."""
    schema = load_air_event_schema(root=root)
    Draft202012Validator(schema).validate(dict(event))
