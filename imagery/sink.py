"""
Imagery — persistence sink (skywatcher-pr).

skywatcher-pr has no satellite-ingest pipeline, so this sink is self-contained:
build a satellite_source_manifest, validate it against the ported contract
schema (schemas/satellite_source_manifest.schema.json), and write accepted
manifests to ``data/satellite_manifests/``.

This is the *only* module that differs between spiderweb-pr and skywatcher-pr.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from . import manifest as manifest_mod
from .models import ImageryResult

_SCHEMA_PATH = config.BASE_DIR / "schemas" / "satellite_source_manifest.schema.json"
_MANIFESTS_DIR = config.BASE_DIR / "data" / "satellite_manifests"


def _validate(doc: dict[str, Any]) -> list[str]:
    """Validate against the manifest schema; return a list of error strings."""
    try:
        import jsonschema
    except Exception as exc:  # pragma: no cover - jsonschema is an imagery dep
        return [f"jsonschema unavailable: {exc}"]
    try:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"schema not found: {_SCHEMA_PATH}"]
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(doc)]


def persist(result: ImageryResult, synthetic: bool = False) -> dict[str, Any]:
    """Build a manifest from ``result``, validate, and write it to disk.

    Returns a result dict: ``persisted`` (bool), ``status`` ("accepted" |
    "rejected"), ``output_path``, and ``errors``. Never raises — a persistence
    failure must not fail the fetch itself.
    """
    doc = manifest_mod.build_manifest(result, synthetic=synthetic)

    errors = _validate(doc)
    if errors:
        return {
            "persisted": False,
            "status": "rejected",
            "output_path": None,
            "errors": errors,
            "manifest": doc,
        }

    try:
        _MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = _MANIFESTS_DIR / f"{ts}_{doc['manifest_id']}.json"
        out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return {
            "persisted": True,
            "status": "accepted",
            "output_path": str(out),
            "errors": [],
            "manifest": doc,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "persisted": False,
            "status": "rejected",
            "output_path": None,
            "errors": [f"write error: {exc}"],
            "manifest": doc,
        }
