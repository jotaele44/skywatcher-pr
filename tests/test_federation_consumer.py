"""Tests for the Skywatcher federation consumer bridge (integration/federation_consumer.py).

The consumer ingests a hub-canonical sibling-producer package (manifest.json +
{observations,alerts,entities}.jsonl), validating every record against its
canonical Hub schema, enforcing manifest count/sha256 integrity and the
prohibited-terminal-label gate, and loading the survivors into a local read-model
SQLite. All fixtures are synthetic and built in a tmp dir (no network, no real DB).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from integration.federation_consumer import (
    FederationConsumerError,
    ingest_package,
    read_package,
    validate_record,
)


def _obs(oid="obs_" + "a" * 32, muni="San Juan", **over):
    row = {
        "observation_id": oid,
        "source_id": "src_" + "b" * 32,
        "entity_id": "ent_" + "c" * 32,
        "observation_type": "airspace_observation",
        "observed_at": "2026-05-20T10:00:00Z",
        "confidence": 0.8,
        "location": {"lat": 18.4, "lon": -66.0, "municipality": muni},
        "attributes": {"signal_type": "FR24_SCREENSHOT"},
        "lineage": {"producer_script": "x", "producer_phase": "p", "source_inputs": ["a"]},
        "synthetic": True,
        "created_at": "2026-05-20T10:00:00Z",
        "extracted_at": "2026-05-20T10:00:00Z",
    }
    row.update(over)
    return row


def _alert(aid="alrt_" + "d" * 32, muni="San Juan", **over):
    row = {
        "alert_id": aid,
        "source_id": "src_" + "b" * 32,
        "module": "AIRSPACE_OPS",
        "alert_type": "loitering_pattern",
        "severity": 2,
        "status": "draft",
        "observed_at": "2026-05-20T10:05:00Z",
        "confidence": 0.7,
        "location": {"lat": 18.4, "lon": -66.0, "municipality": muni},
        "attributes": {"operator_action": "review_context_only"},
        "lineage": {"producer_script": "x", "producer_phase": "p", "source_inputs": ["a"]},
        "synthetic": True,
        "created_at": "2026-05-20T10:05:00Z",
        "extracted_at": "2026-05-20T10:05:00Z",
    }
    row.update(over)
    return row


def _write_package(pkg_dir: Path, streams: dict, *, producer="aguayluz-pr", mode="test"):
    """Write a hub-canonical package dir with a self-consistent manifest."""
    pkg_dir.mkdir(parents=True, exist_ok=True)
    schema_map = {
        "observations": "federation_observation.schema.json",
        "alerts": "federation_alert.schema.json",
        "entities": "federation_entity.schema.json",
    }
    files = []
    for stream, rows in streams.items():
        fname = f"{stream}.jsonl"
        fpath = pkg_dir / fname
        fpath.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
        files.append({
            "filename": fname, "stream": stream, "record_count": len(rows),
            "sha256": hashlib.sha256(fpath.read_bytes()).hexdigest(),
            "schema_id": schema_map[stream],
        })
    manifest = {
        "package_id": "pkg_" + "e" * 32, "producer": producer,
        "export_contract_version": "1.0.0", "mode": mode,
        "created_at": "2026-05-20T00:00:00Z",
        "federation": {"producer_repo": producer, "hub_parent": "thehub-pr"},
        "files": files,
    }
    (pkg_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return pkg_dir


def test_ingest_valid_package(tmp_path):
    pkg = _write_package(tmp_path / "pkg", {
        "observations": [_obs()],
        "alerts": [_alert()],
    })
    db = str(tmp_path / "consumer.db")
    summary = ingest_package(Path(pkg), db)
    assert summary["producer"] == "aguayluz-pr"
    assert summary["streams"]["observations"]["ingested"] == 1
    assert summary["streams"]["alerts"]["ingested"] == 1
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM consumed_observations").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM consumed_alerts").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM consumed_producers").fetchone()[0] == 1
    # municipality is projected out for cross-reference joins.
    assert conn.execute("SELECT municipality FROM consumed_alerts").fetchone()[0] == "San Juan"
    conn.close()


def test_missing_manifest_rejected(tmp_path):
    pkg = tmp_path / "nomanifest"
    pkg.mkdir()
    (pkg / "observations.jsonl").write_text(json.dumps(_obs()) + "\n")
    with pytest.raises(FederationConsumerError, match="manifest.json"):
        read_package(pkg)


def test_sha256_tamper_rejected(tmp_path):
    pkg = _write_package(tmp_path / "pkg", {"observations": [_obs()]})
    # mutate the bytes after the manifest recorded the original sha256
    (pkg / "observations.jsonl").write_text(json.dumps(_obs(confidence=0.1)) + "\n")
    with pytest.raises(FederationConsumerError, match="sha256 mismatch"):
        read_package(pkg)


def test_record_count_mismatch_rejected(tmp_path):
    pkg = _write_package(tmp_path / "pkg", {"observations": [_obs()]})
    # Write 2 rows and refresh the sha256 (so the byte check passes) but leave the
    # manifest record_count at 1 — read_package must catch the count mismatch.
    p = pkg / "observations.jsonl"
    rows = [_obs(), _obs(oid="obs_" + "f" * 32)]
    p.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    man = json.loads((pkg / "manifest.json").read_text())
    man["files"][0]["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()  # count stays 1
    (pkg / "manifest.json").write_text(json.dumps(man))
    with pytest.raises(FederationConsumerError, match="record_count"):
        read_package(pkg)


def test_invalid_record_held_not_ingested(tmp_path):
    bad = _obs(oid="not_a_valid_obs_id")  # violates ^obs_[a-f0-9]{32}$
    pkg = _write_package(tmp_path / "pkg", {"observations": [_obs(), bad]})
    db = str(tmp_path / "c.db")
    summary = ingest_package(Path(pkg), db)
    st = summary["streams"]["observations"]
    assert st["valid"] == 1 and st["rejected"] == 1 and st["ingested"] == 1
    assert st["rejects"][0]["id"] == "not_a_valid_obs_id"


def test_prohibited_label_rejected():
    # defense-in-depth: a terminal-accept label anywhere fails validation even
    # when the record is otherwise schema-valid.
    rec = _alert(attributes={"disposition": "confirmed"})
    errors = validate_record(rec, "alerts")
    assert any("prohibited" in e for e in errors)


def test_alert_lifecycle_validated_is_allowed():
    # bare lifecycle states are legitimate and must NOT trip the prohibited gate.
    rec = _alert(status="validated")
    assert validate_record(rec, "alerts") == []


def test_unmodeled_streams_skipped(tmp_path):
    pkg = _write_package(tmp_path / "pkg", {"observations": [_obs()]})
    # add a sources file + manifest entry the consumer does not model
    src_path = pkg / "sources.jsonl"
    src_path.write_text(json.dumps({"source_id": "src_" + "0" * 32}) + "\n")
    man = json.loads((pkg / "manifest.json").read_text())
    man["files"].append({
        "filename": "sources.jsonl", "stream": "sources", "record_count": 1,
        "sha256": hashlib.sha256(src_path.read_bytes()).hexdigest(),
        "schema_id": "federation_source.schema.json",
    })
    (pkg / "manifest.json").write_text(json.dumps(man))
    summary = ingest_package(Path(pkg), str(tmp_path / "c.db"))
    assert "sources" in summary["skipped_streams"]
    assert "sources" not in summary["streams"]


def test_dry_run_creates_no_db(tmp_path):
    pkg = _write_package(tmp_path / "pkg", {"observations": [_obs()]})
    db = tmp_path / "c.db"
    summary = ingest_package(Path(pkg), str(db), dry_run=True)
    assert summary["dry_run"] is True
    assert summary["streams"]["observations"]["valid"] == 1
    assert summary["streams"]["observations"]["ingested"] == 0
    assert not db.exists()
