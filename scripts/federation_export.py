#!/usr/bin/env python3
"""Project a Skywatcher airspace observation package into PRII canonical streams.

Maps the airspace_observation model onto the Hub's canonical contract:
  * each observation        -> one `entities` row (entity_type=airspace_observation)
  * each distinct source    -> one `sources` row  + a `sensor_source` entity
  * each distinct municipality -> one `entities` row (entity_type=municipality)
  * observation -> source       -> `relationships` row (detected_by)
  * observation -> municipality -> `relationships` row (located_in)

Reads `observations.csv` + `sources.json` from an airspace package dir and writes
`exports/federation/{sources,entities,relationships}.jsonl` + a Hub-conformant
`manifest.json`. Deterministic `src_/ent_/rel_` ids (sha256). Stdlib only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
PRODUCER = "skywatcher-pr"
CONTRACT_VERSION = "1.0.0"
PRODUCER_SCRIPT = "scripts/federation_export.py"
TIER_CONFIDENCE = {"T1": 0.9, "T2": 0.7, "T3": 0.5, "T4": 0.3}

STREAM_SCHEMA = {
    "sources": "federation_source.schema.json",
    "entities": "federation_entity.schema.json",
    "relationships": "federation_relationship.schema.json",
}


def _fid(prefix: str, *parts: Any) -> str:
    return f"{prefix}_{hashlib.sha256('|'.join(str(p) for p in parts).encode()).hexdigest()[:32]}"


def _norm(name: str) -> str:
    return " ".join(str(name).strip().upper().split())


def _bool(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def _lineage(phase: str, inputs: List[str]) -> Dict[str, Any]:
    return {
        "producer_script": PRODUCER_SCRIPT,
        "producer_phase": phase,
        "source_inputs": inputs,
        "extraction_method": "deterministic_observation_projection",
    }


def build_streams(observations: List[Dict[str, Any]], sources: List[Dict[str, Any]], now: str) -> Dict[str, List[Dict[str, Any]]]:
    inputs = ["observations.csv", "sources.json"]
    src_rows: Dict[str, Dict[str, Any]] = {}
    src_entity_id: Dict[str, str] = {}
    entities: Dict[str, Dict[str, Any]] = {}
    relationships: Dict[str, Dict[str, Any]] = {}

    # sources -> sources rows + sensor_source entities
    for s in sources:
        raw_sid = s.get("source_id")
        synthetic = s.get("provenance_status", "").startswith("synthetic")
        sid = _fid("src", raw_sid)
        src_rows[raw_sid] = {
            "source_id": sid,
            "source_type": s.get("source_type") or "unknown",
            "source_name": s.get("source_path") or raw_sid,
            "source_ref": s.get("sha256") or raw_sid,
            "confidence": 1.0,
            "lineage": _lineage("SOURCE_REGISTRY", inputs),
            "synthetic": synthetic,
            "created_at": s.get("retrieved_at") or now,
            "extracted_at": now,
        }
        ent_id = _fid("ent", "source", raw_sid)
        src_entity_id[raw_sid] = ent_id
        entities[ent_id] = {
            "entity_id": ent_id,
            "source_id": sid,
            "name": s.get("source_path") or raw_sid,
            "normalized_name": _norm(s.get("source_path") or raw_sid),
            "entity_type": "sensor_source",
            "jurisdiction": "PR",
            "confidence": 1.0,
            "lineage": _lineage("SOURCE_ENTITY", inputs),
            "synthetic": synthetic,
            "created_at": s.get("retrieved_at") or now,
            "extracted_at": now,
        }

    for obs in observations:
        raw_sid = obs.get("source_id")
        sid = src_rows.get(raw_sid, {}).get("source_id") or _fid("src", raw_sid)
        synthetic = _bool(obs.get("synthetic"))
        confidence = float(obs.get("confidence") or TIER_CONFIDENCE.get(obs.get("evidence_tier"), 0.5))
        when = obs.get("event_datetime") or now
        obs_id = obs.get("observation_id")

        ent_id = _fid("ent", "observation", obs_id)
        entities[ent_id] = {
            "entity_id": ent_id,
            "source_id": sid,
            "name": obs.get("location_name") or obs_id,
            "normalized_name": _norm(obs.get("location_name") or obs_id),
            "entity_type": "airspace_observation",
            "jurisdiction": "PR",
            "confidence": confidence,
            "lineage": _lineage("OBSERVATION_ENTITY", inputs),
            "synthetic": synthetic,
            "created_at": when,
            "extracted_at": now,
        }

        # detected_by (observation -> source entity)
        tgt = src_entity_id.get(raw_sid) or _fid("ent", "source", raw_sid)
        rid = _fid("rel", ent_id, "detected_by", tgt)
        relationships[rid] = _rel(rid, sid, ent_id, tgt, "detected_by", confidence, synthetic, when, now)

        # located_in (observation -> municipality)
        muni = obs.get("municipality")
        if muni:
            muni_id = _fid("ent", "municipality", _norm(muni))
            entities.setdefault(muni_id, {
                "entity_id": muni_id, "source_id": sid, "name": muni,
                "normalized_name": _norm(muni), "entity_type": "municipality",
                "jurisdiction": "PR", "confidence": 0.95,
                "lineage": _lineage("MUNICIPALITY_ENTITY", inputs),
                "synthetic": synthetic, "created_at": when, "extracted_at": now,
            })
            rid = _fid("rel", ent_id, "located_in", muni_id)
            relationships[rid] = _rel(rid, sid, ent_id, muni_id, "located_in", confidence, synthetic, when, now)

    return {
        "sources": list(src_rows.values()),
        "entities": list(entities.values()),
        "relationships": list(relationships.values()),
    }


def _rel(rid, sid, src_ent, tgt_ent, rtype, confidence, synthetic, created, now):
    return {
        "relationship_id": rid, "source_id": sid,
        "source_entity_id": src_ent, "target_entity_id": tgt_ent,
        "relationship_type": rtype, "evidence_source_id": sid,
        "confidence": confidence, "lineage": _lineage("RELATIONSHIP", ["observations.csv"]),
        "synthetic": synthetic, "created_at": created, "extracted_at": now,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_package(streams: Dict[str, List[Dict[str, Any]]], out_dir: Path, mode: str, now: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for stream in ("sources", "entities", "relationships"):
        rows = streams[stream]
        if not rows:
            continue
        fpath = out_dir / f"{stream}.jsonl"
        fpath.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
        files.append({"filename": f"{stream}.jsonl", "stream": stream, "record_count": len(rows),
                      "sha256": _sha256(fpath), "schema_id": STREAM_SCHEMA[stream]})
    digest = hashlib.sha256(
        ("|".join(f"{f['filename']}:{f['sha256']}" for f in files) + f"|{mode}").encode()
    ).hexdigest()[:32]
    manifest = {
        "package_id": f"pkg_{digest}", "producer": PRODUCER,
        "export_contract_version": CONTRACT_VERSION, "mode": mode,
        "created_at": now, "extracted_at": now,
        "federation": {"producer_repo": PRODUCER, "hub_parent": "thehub-pr"},
        "files": files,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return out_dir / "manifest.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="Export Skywatcher observations as PRII canonical streams.")
    ap.add_argument("--package", default=str(REPO_ROOT / "exports/examples/synthetic_airspace_package"))
    ap.add_argument("--out", default=str(REPO_ROOT / "exports/federation"))
    ap.add_argument("--mode", default="test", choices=["test", "production"])
    args = ap.parse_args()

    pkg = Path(args.package)
    with (pkg / "observations.csv").open() as fh:
        observations = list(csv.DictReader(fh))
    sources = json.loads((pkg / "sources.json").read_text())
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    streams = build_streams(observations, sources, now)

    if args.mode == "production":
        synthetic = [r for s in streams.values() for r in s if r.get("synthetic")]
        if synthetic:
            print(f"FAIL — {len(synthetic)} synthetic rows are not allowed in production mode")
            return 1

    manifest_path = write_package(streams, Path(args.out), args.mode, now)
    counts = {k: len(v) for k, v in streams.items()}
    print(f"wrote {manifest_path} — {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
