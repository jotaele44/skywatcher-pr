"""Immutable local persistence for Space-Track source manifestations."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import Manifestation, SchemaSnapshot, Watermark


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )
        + "\n"
    ).encode("utf-8")


class SpaceTrackStore:
    """Content-addressed raw store plus restartable control metadata."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def freeze_raw(self, manifestation: Manifestation, payload: bytes) -> Path:
        base = self.root / "raw" / manifestation.source_id / manifestation.raw_sha256
        raw_path = base / "payload.bin"
        manifest_path = base / "manifest.json"

        if raw_path.exists():
            existing = raw_path.read_bytes()
            if existing != payload:
                raise RuntimeError("content-addressed payload collision")
        else:
            _atomic_write(raw_path, payload)

        manifest_bytes = _canonical_json(asdict(manifestation))
        if manifest_path.exists() and manifest_path.read_bytes() != manifest_bytes:
            raise RuntimeError("manifestation metadata collision for identical raw SHA256")
        if not manifest_path.exists():
            _atomic_write(manifest_path, manifest_bytes)
        return raw_path

    def save_schema(self, snapshot: SchemaSnapshot) -> Path:
        path = self.root / "schemas" / f"{snapshot.source_id}.json"
        _atomic_write(path, _canonical_json(asdict(snapshot)))
        return path

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
