"""Pinned-compatible fallback for thehub-pr's small export helper package."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def fid(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()[:32]
    return f"{prefix}_{digest}"


def norm(name: str) -> str:
    return " ".join(str(name).strip().upper().split())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
