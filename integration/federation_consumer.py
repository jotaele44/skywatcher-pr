"""SKYWATCHER FEDERATION CONSUMER BRIDGE (sibling-producer ingest boundary)

Skywatcher is a federation *producer* (it emits canonical sources / entities /
relationships / observations / alerts via ``scripts/federation_export.py``). This
module is the reciprocal *consumer* boundary: it ingests a hub-canonical package
emitted by a **sibling** producer (e.g. aguayluz-pr grid/water alerts, spiderweb-pr
spatial observations) so Skywatcher's airspace analysis can be cross-referenced
against sibling signals — by shared ``location.municipality`` — inside Skywatcher.

It consumes the three cross-producer signal streams the airspace context can use:

    observations -> federation_observation.schema.json
    alerts       -> federation_alert.schema.json
    entities     -> federation_entity.schema.json

Streams it does not model (sources / relationships / funding_awards / transactions)
are skipped with an explicit note in the summary rather than silently dropped.

Policy (candidate-only, no auto-confirmation — mirrors the Spiderweb bridge):
  * the package ``manifest.json`` is required and its per-file ``record_count`` +
    ``sha256`` are verified against the bytes on disk, so a hand-assembled or
    tampered JSONL is rejected rather than trusted as canonical;
  * every record is validated against its canonical Hub schema; records that fail
    validation are rejected (held), never ingested;
  * defense-in-depth: any record carrying a terminal-accept label (e.g.
    "confirmed", "verified_event") is rejected even if it passed schema
    validation — sibling signals enter Skywatcher as review context, never as a
    confirmed verdict or an operational cue.

It performs NO screenshot processing and creates only the minimal read-model
tables (``consumed_observations`` / ``consumed_alerts`` / ``consumed_entities`` +
a ``consumed_producers`` provenance row) that Skywatcher's cross-reference logic
reads. Stdlib + jsonschema only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas"

CONSUMER_ADAPTER_VERSION = "skywatcher_federation_consumer_v0.1.0"

# Streams this consumer models, mapped to their canonical Hub schema file.
STREAM_SCHEMA = {
    "observations": "federation_observation.schema.json",
    "alerts": "federation_alert.schema.json",
    "entities": "federation_entity.schema.json",
}

# Defense-in-depth: sibling rows must never assert a confirmed/verified verdict.
# (Bare alert-lifecycle states like "validated"/"active"/"closed" are legitimate
# and intentionally NOT listed — only terminal-accept confidence labels are.)
PROHIBITED_LABELS = {
    "confirmed",
    "confirmed_aircraft_event",
    "confirmed_anomaly",
    "confirmed_route",
    "verified_event",
    "validated_aircraft_event",
}

_PRODUCERS_DDL = """
CREATE TABLE IF NOT EXISTS consumed_producers (
    package_id TEXT PRIMARY KEY,
    producer TEXT,
    mode TEXT,
    created_at TEXT,
    consumer_adapter TEXT
)
"""

_OBSERVATIONS_DDL = """
CREATE TABLE IF NOT EXISTS consumed_observations (
    observation_id TEXT PRIMARY KEY,
    package_id TEXT,
    producer TEXT,
    source_id TEXT,
    entity_id TEXT,
    observation_type TEXT,
    observed_at TEXT,
    lat REAL, lon REAL, municipality TEXT,
    confidence REAL,
    synthetic INTEGER,
    attributes_json TEXT,
    FOREIGN KEY(package_id) REFERENCES consumed_producers(package_id)
)
"""

_ALERTS_DDL = """
CREATE TABLE IF NOT EXISTS consumed_alerts (
    alert_id TEXT PRIMARY KEY,
    package_id TEXT,
    producer TEXT,
    source_id TEXT,
    entity_id TEXT,
    module TEXT,
    alert_type TEXT,
    severity INTEGER,
    status TEXT,
    observed_at TEXT,
    lat REAL, lon REAL, municipality TEXT,
    confidence REAL,
    synthetic INTEGER,
    attributes_json TEXT,
    FOREIGN KEY(package_id) REFERENCES consumed_producers(package_id)
)
"""

_ENTITIES_DDL = """
CREATE TABLE IF NOT EXISTS consumed_entities (
    entity_id TEXT PRIMARY KEY,
    package_id TEXT,
    producer TEXT,
    source_id TEXT,
    entity_type TEXT,
    name TEXT,
    lat REAL, lon REAL, municipality TEXT,
    confidence REAL,
    synthetic INTEGER,
    FOREIGN KEY(package_id) REFERENCES consumed_producers(package_id)
)
"""


class FederationConsumerError(RuntimeError):
    pass


def load_schema(stream: str) -> Dict[str, Any]:
    schema_file = STREAM_SCHEMA.get(stream)
    if schema_file is None:
        raise FederationConsumerError(f"no schema mapped for stream: {stream!r}")
    path = SCHEMA_DIR / schema_file
    if not path.is_file():
        raise FederationConsumerError(f"canonical schema missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _has_prohibited_label(record: Dict[str, Any]) -> bool:
    def _scan(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in PROHIBITED_LABELS
        if isinstance(value, dict):
            return any(_scan(v) for v in value.values())
        if isinstance(value, list):
            return any(_scan(v) for v in value)
        return False

    return _scan(record)


def validate_record(
    record: Dict[str, Any], stream: str, schema: Optional[Dict[str, Any]] = None
) -> List[str]:
    """Return a list of validation errors for one record (empty == valid)."""
    from jsonschema import Draft7Validator  # lazy: declared dependency

    schema = schema or load_schema(stream)
    validator = Draft7Validator(
        schema, format_checker=Draft7Validator.FORMAT_CHECKER
    )
    errors = [f"{list(e.path)}: {e.message}" for e in validator.iter_errors(record)]
    if _has_prohibited_label(record):
        errors.append("prohibited terminal-accept label present")
    return errors


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def read_package(package_dir: Path) -> Dict[str, Any]:
    """Read + verify a hub-canonical sibling package directory.

    Requires ``manifest.json``; for every file entry whose stream this consumer
    models, verifies the on-disk ``record_count`` and ``sha256`` against the
    manifest before returning the parsed rows. Unmodeled streams are recorded as
    ``skipped`` rather than read.
    """
    package_dir = Path(package_dir)
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FederationConsumerError(
            f"package missing manifest.json: {manifest_path}. "
            f"Expected a hub-canonical producer package directory."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    streams: Dict[str, List[Dict[str, Any]]] = {}
    skipped: List[str] = []
    for entry in manifest.get("files", []):
        stream = entry.get("stream")
        filename = entry.get("filename")
        if stream not in STREAM_SCHEMA:
            if stream not in skipped:
                skipped.append(stream)
            continue
        fpath = package_dir / filename
        if not fpath.is_file():
            raise FederationConsumerError(
                f"manifest lists {filename!r} but it is missing from {package_dir}"
            )
        # The canonical manifest contract (federation_export_manifest.schema.json)
        # requires both sha256 and record_count on every file entry. Enforce their
        # PRESENCE for modeled streams before trusting the bytes — otherwise a
        # hand-assembled partial manifest that simply omits the integrity fields
        # would skip verification and get schema-valid records ingested as if
        # canonical. Missing integrity metadata == not a canonical package.
        declared_sha = entry.get("sha256")
        declared_count = entry.get("record_count")
        if not declared_sha or declared_count is None:
            missing = [
                name for name, val in (("sha256", declared_sha), ("record_count", declared_count))
                if val in (None, "")
            ]
            raise FederationConsumerError(
                f"{filename}: manifest entry missing required integrity field(s) "
                f"{missing}; a canonical package must declare sha256 and record_count."
            )
        actual_sha = hashlib.sha256(fpath.read_bytes()).hexdigest()
        if declared_sha != actual_sha:
            raise FederationConsumerError(
                f"{filename}: sha256 mismatch "
                f"(manifest {declared_sha[:12]}… != file {actual_sha[:12]}…)"
            )
        rows = _read_jsonl(fpath)
        if declared_count != len(rows):
            raise FederationConsumerError(
                f"{filename}: manifest record_count={declared_count} != {len(rows)} rows present"
            )
        streams[stream] = rows

    return {"manifest": manifest, "streams": streams, "skipped_streams": skipped}


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute(_PRODUCERS_DDL)
    conn.execute(_OBSERVATIONS_DDL)
    conn.execute(_ALERTS_DDL)
    conn.execute(_ENTITIES_DDL)
    conn.commit()


def _loc(rec: Dict[str, Any]) -> Dict[str, Any]:
    loc = rec.get("location") or {}
    return {
        "lat": loc.get("lat"),
        "lon": loc.get("lon"),
        "municipality": loc.get("municipality"),
    }


def _ingest_observation(conn, package_id, producer, rec) -> None:
    loc = _loc(rec)
    conn.execute(
        """INSERT OR REPLACE INTO consumed_observations
           (observation_id, package_id, producer, source_id, entity_id,
            observation_type, observed_at, lat, lon, municipality,
            confidence, synthetic, attributes_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            rec["observation_id"], package_id, producer, rec.get("source_id"),
            rec.get("entity_id"), rec.get("observation_type"), rec.get("observed_at"),
            loc["lat"], loc["lon"], loc["municipality"], rec.get("confidence"),
            1 if rec.get("synthetic") else 0, json.dumps(rec.get("attributes") or {}, sort_keys=True),
        ),
    )


def _ingest_alert(conn, package_id, producer, rec) -> None:
    loc = _loc(rec)
    conn.execute(
        """INSERT OR REPLACE INTO consumed_alerts
           (alert_id, package_id, producer, source_id, entity_id, module,
            alert_type, severity, status, observed_at, lat, lon, municipality,
            confidence, synthetic, attributes_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            rec["alert_id"], package_id, producer, rec.get("source_id"),
            rec.get("entity_id"), rec.get("module"), rec.get("alert_type"),
            rec.get("severity"), rec.get("status"), rec.get("observed_at"),
            loc["lat"], loc["lon"], loc["municipality"], rec.get("confidence"),
            1 if rec.get("synthetic") else 0, json.dumps(rec.get("attributes") or {}, sort_keys=True),
        ),
    )


def _ingest_entity(conn, package_id, producer, rec) -> None:
    loc = _loc(rec)
    conn.execute(
        """INSERT OR REPLACE INTO consumed_entities
           (entity_id, package_id, producer, source_id, entity_type, name,
            lat, lon, municipality, confidence, synthetic)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            rec["entity_id"], package_id, producer, rec.get("source_id"),
            rec.get("entity_type"), rec.get("name"),
            loc["lat"], loc["lon"], loc["municipality"], rec.get("confidence"),
            1 if rec.get("synthetic") else 0,
        ),
    )


_INGESTORS = {
    "observations": _ingest_observation,
    "alerts": _ingest_alert,
    "entities": _ingest_entity,
}


def ingest_package(
    package_dir: Path,
    db_path: str,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Validate and (unless dry_run) ingest a sibling producer's canonical package.

    Returns a summary: per-stream total / valid / ingested / rejected counts +
    per-reject reasons. Ingestion is transactional; any invalid record is held
    (not ingested), and the whole package is committed atomically.
    """
    package = read_package(package_dir)
    manifest = package["manifest"]
    package_id = manifest.get("package_id", "")
    producer = manifest.get("producer", "")

    per_stream: Dict[str, Dict[str, Any]] = {}
    valid_by_stream: Dict[str, List[Dict[str, Any]]] = {}
    for stream, rows in package["streams"].items():
        schema = load_schema(stream)
        valid: List[Dict[str, Any]] = []
        rejects: List[Dict[str, Any]] = []
        id_key = {
            "observations": "observation_id",
            "alerts": "alert_id",
            "entities": "entity_id",
        }[stream]
        for rec in rows:
            errors = validate_record(rec, stream, schema)
            if errors:
                rejects.append({"id": rec.get(id_key), "errors": errors})
            else:
                valid.append(rec)
        valid_by_stream[stream] = valid
        per_stream[stream] = {
            "total": len(rows),
            "valid": len(valid),
            "ingested": 0,
            "rejected": len(rejects),
            "rejects": rejects,
        }

    if not dry_run and any(valid_by_stream.values()):
        conn = sqlite3.connect(db_path)
        try:
            _ensure_tables(conn)
            conn.execute(
                """INSERT OR REPLACE INTO consumed_producers
                   (package_id, producer, mode, created_at, consumer_adapter)
                   VALUES (?,?,?,?,?)""",
                (package_id, producer, manifest.get("mode"),
                 manifest.get("created_at"), CONSUMER_ADAPTER_VERSION),
            )
            for stream, valid in valid_by_stream.items():
                ingest = _INGESTORS[stream]
                for rec in valid:
                    ingest(conn, package_id, producer, rec)
                per_stream[stream]["ingested"] = len(valid)
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.close()

    return {
        "package": str(package_dir),
        "package_id": package_id,
        "producer": producer,
        "streams": per_stream,
        "skipped_streams": package["skipped_streams"],
        "dry_run": dry_run,
        "adapter_version": CONSUMER_ADAPTER_VERSION,
    }
