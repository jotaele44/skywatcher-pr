"""Bounded artifact discovery and read-only file/database helpers."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
from functools import lru_cache
from urllib.parse import quote
from pathlib import Path
from typing import Any, Iterable

from .base import ArtifactRef

HASH_LIMIT_BYTES = 64 * 1024 * 1024


def bounded_paths(
    root: Path,
    *,
    env_var: str | None = None,
    defaults: Iterable[str] = (),
) -> list[tuple[Path, str | None]]:
    candidates: list[tuple[Path, str | None]] = []
    seen: set[str] = set()
    if env_var:
        configured = os.environ.get(env_var, "").strip()
        if configured:
            path = Path(configured).expanduser()
            key = str(path.resolve(strict=False))
            if key not in seen:
                candidates.append((path, env_var))
                seen.add(key)
    for relative in defaults:
        path = root / relative
        key = str(path.resolve(strict=False))
        if key not in seen:
            candidates.append((path, None))
            seen.add(key)
    return candidates


@lru_cache(maxsize=256)
def _file_sha256_cached(path_text: str, size: int, modified_ns: int) -> str | None:
    if size > HASH_LIMIT_BYTES:
        return None
    digest = hashlib.sha256()
    with Path(path_text).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_sha256(path: Path) -> str | None:
    try:
        stat = path.stat()
        return _file_sha256_cached(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    except OSError:
        return None


def artifact_ref(
    path: Path,
    *,
    kind: str,
    configured_by: str | None = None,
    record_count: int | None = None,
    status: str = "candidate",
    error: str | None = None,
) -> ArtifactRef:
    exists = path.is_file()
    size = path.stat().st_size if exists else None
    return ArtifactRef(
        path=str(path),
        kind=kind,
        exists=exists,
        size_bytes=size,
        sha256=file_sha256(path) if exists else None,
        configured_by=configured_by,
        record_count=record_count,
        status=status,
        error=error,
    )


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_json_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("rows", "items", "captures", "profiles", "flights", "routes", "states"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, dict)]
    return [dict(payload)]


def read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(dict(value))
    return rows


def read_structured_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_csv_rows(path)
    if suffix in {".jsonl", ".ndjson"}:
        return read_jsonl_rows(path)
    if suffix == ".json":
        return read_json_rows(path)
    raise ValueError(f"unsupported structured artifact: {path.suffix}")


def open_sqlite_readonly(path: Path) -> sqlite3.Connection:
    absolute = path.expanduser().resolve(strict=True)
    encoded = quote(absolute.as_posix(), safe="/:\\")
    connection = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def sqlite_table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def sqlite_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def sqlite_rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]
