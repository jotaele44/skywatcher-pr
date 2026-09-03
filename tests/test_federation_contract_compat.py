"""Federation canonical-export contract-compat test (hub-facing).

Pins the manifest envelope produced by ``scripts/federation_export.py``
``write_package`` against the hub's contract: the exact top-level key set,
the federation handshake block, the per-file entries, and validity against
the vendored copy of thehub-pr's ``federation_export_manifest`` schema
(``schemas/federation_export_manifest.schema.json``). A producer-side change
that alters any of these breaks this test before it can silently break the
hub's consumer.
"""

import json
from pathlib import Path

import jsonschema

from scripts.federation_export import build_streams, write_package

REPO = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO / "schemas" / "federation_export_manifest.schema.json"

FIXED_NOW = "2026-01-01T00:00:00Z"
MODE = "test"

EXPECTED_MANIFEST_KEYS = {
    "package_id", "producer", "export_contract_version", "mode",
    "created_at", "extracted_at", "federation", "files",
}

OBS = [{
    "observation_id": "o1", "event_datetime": "2026-05-20T10:00:00Z",
    "location_name": "San Juan point", "municipality": "San Juan",
    "lat": "18.4", "lon": "-66.0", "signal_type": "FR24_SCREENSHOT",
    "source_id": "s1", "source_type": "screenshot", "evidence_tier": "T2",
    "confidence": "0.82", "geometry_status": "approximate", "temporal_status": "exact",
    "lineage_id": "l1", "synthetic": "false",
}]
SRC = [{
    "source_id": "s1", "source_type": "screenshot", "source_path": "fr24.png",
    "sha256": "abc123", "retrieved_at": "2026-05-20T00:00:00Z", "provenance_status": "verified",
}]


def _manifest(tmp_path):
    streams = build_streams(OBS, SRC, FIXED_NOW)
    manifest_path = write_package(streams, tmp_path, MODE, FIXED_NOW)
    return json.loads(manifest_path.read_text())


def test_manifest_top_level_keys_exact(tmp_path):
    manifest = _manifest(tmp_path)
    assert set(manifest) == EXPECTED_MANIFEST_KEYS


def test_federation_handshake_block(tmp_path):
    manifest = _manifest(tmp_path)
    assert manifest["federation"]["hub_parent"] == "thehub-pr"
    assert manifest["federation"]["producer_repo"] == "skywatcher-pr"


def test_file_entries_carry_required_fields(tmp_path):
    manifest = _manifest(tmp_path)
    assert manifest["files"]
    for f in manifest["files"]:
        assert set(f) >= {"filename", "stream", "record_count", "sha256", "schema_id"}


def test_manifest_validates_against_vendored_hub_schema(tmp_path):
    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.validate(_manifest(tmp_path), schema)


def test_package_id_is_deterministic(tmp_path):
    a = _manifest(tmp_path / "a")
    b = _manifest(tmp_path / "b")
    assert a["package_id"] == b["package_id"]
    assert a == b
