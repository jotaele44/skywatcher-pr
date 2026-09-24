"""Immutable local persistence for Space-Track source manifestations."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any

from .models import Manifestation, NormalizedBatch, SchemaSnapshot, Watermark


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def _json_default(value: Any) -> str:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=_json_default,
        )
        + "\n"
    ).encode("utf-8")


def _key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SpaceTrackStore:
    """Content-addressed raw store plus restartable control metadata."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def freeze_raw(self, manifestation: Manifestation, payload: bytes) -> Path:
        payload_path = (
            self.root
            / "raw"
            / manifestation.source_id
            / manifestation.raw_sha256
            / "payload.bin"
        )
        if payload_path.exists():
            existing = payload_path.read_bytes()
            if existing != payload:
                raise RuntimeError("content-addressed payload collision")
        else:
            _atomic_write(payload_path, payload)

        manifest_bytes = _canonical_json(asdict(manifestation))
        manifest_id = hashlib.sha256(manifest_bytes).hexdigest()
        manifest_path = (
            self.root
            / "manifestations"
            / manifestation.source_id
            / f"{manifest_id}.json"
        )
        if manifest_path.exists() and manifest_path.read_bytes() != manifest_bytes:
            raise RuntimeError("manifestation identity collision")
        if not manifest_path.exists():
            _atomic_write(manifest_path, manifest_bytes)
        return payload_path

    def query_seen(self, source_id: str, query: str) -> bool:
        return (self.root / "query_receipts" / source_id / f"{_key(query)}.json").exists()

    def record_query_receipt(self, manifestation: Manifestation) -> Path:
        path = (
            self.root
            / "query_receipts"
            / manifestation.source_id
            / f"{_key(manifestation.query)}.json"
        )
        payload = _canonical_json(
            {
                "source_id": manifestation.source_id,
                "query": manifestation.query,
                "retrieved_utc": manifestation.retrieved_utc,
                "raw_sha256": manifestation.raw_sha256,
            }
        )
        if path.exists() and path.read_bytes() != payload:
            raise RuntimeError("query-once receipt already exists with different manifestation")
        if not path.exists():
            _atomic_write(path, payload)
        return path


    def freeze_normalized(self, batch: NormalizedBatch) -> Path:
        payload = _canonical_json(asdict(batch))
        batch_id = hashlib.sha256(payload).hexdigest()
        path = self.root / "normalized" / batch.source_id / f"{batch_id}.json"
        if path.exists() and path.read_bytes() != payload:
            raise RuntimeError("normalized batch identity collision")
        if not path.exists():
            _atomic_write(path, payload)
        return path

    def load_normalized_batches(self, source_id: str) -> tuple[NormalizedBatch, ...]:
        root = self.root / "normalized" / source_id
        if not root.exists():
            return ()
        batches: list[NormalizedBatch] = []
        for path in sorted(root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["rows"] = tuple(dict(row) for row in payload.get("rows", ()))
            batches.append(NormalizedBatch(**payload))
        batches.sort(key=lambda item: (item.retrieved_utc, item.raw_sha256))
        return tuple(batches)

    def freeze_materialization(self, name: str, value: Any) -> tuple[Path, str]:
        if not name or any(part in name for part in ("/", "\\", "..")):
            raise ValueError("materialization name must be a simple path-safe token")
        payload = _canonical_json(value)
        digest = hashlib.sha256(payload).hexdigest()
        version_path = self.root / "materialized" / name / f"{digest}.json"
        if not version_path.exists():
            _atomic_write(version_path, payload)
        current_path = self.root / "materialized" / name / "current.json"
        _atomic_write(current_path, payload)
        return version_path, digest

    def save_schema(self, snapshot: SchemaSnapshot, *, accepted: bool) -> Path:
        payload = _canonical_json(asdict(snapshot))
        version_path = (
            self.root
            / "schemas"
            / snapshot.source_id
            / "observed"
            / f"{snapshot.canonical_sha256}.json"
        )
        if not version_path.exists():
            _atomic_write(version_path, payload)
        if accepted:
            accepted_path = self.root / "schemas" / snapshot.source_id / "accepted.json"
            _atomic_write(accepted_path, payload)
        return version_path

    def load_schema(self, source_id: str) -> SchemaSnapshot | None:
        path = self.root / "schemas" / source_id / "accepted.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["fields"] = tuple(payload.get("fields", ()))
        return SchemaSnapshot(**payload)

    def save_watermark(self, watermark: Watermark) -> Path:
        path = self.root / "watermarks" / f"{watermark.source_id}.json"
        _atomic_write(path, _canonical_json(asdict(watermark)))
        return path

    def load_watermark(self, source_id: str) -> Watermark | None:
        path = self.root / "watermarks" / f"{source_id}.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return Watermark(**payload)

    def save_status(self, payload: dict[str, Any]) -> Path:
        path = self.root / "status.json"
        _atomic_write(path, _canonical_json(payload))
        return path
