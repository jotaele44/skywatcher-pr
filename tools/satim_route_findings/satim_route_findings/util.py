"""Shared deterministic helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path


def stable_id(prefix: str, *parts: object, length: int = 16) -> str:
    """Create a deterministic short identifier from stringable parts."""

    payload = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}:{digest}"


def safe_float(value: object, default: float = 0.0) -> float:
    """Parse a float while tolerating blank cells."""

    try:
        text = "" if value is None else str(value).strip()
        if not text:
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def safe_int(value: object, default: int = 0) -> int:
    """Parse an integer while tolerating blank cells and decimal strings."""

    try:
        text = "" if value is None else str(value).strip()
        if not text:
            return default
        return int(float(text))
    except (TypeError, ValueError):
        return default


def require_safe_output_dir(input_dir: str | Path, output_dir: str | Path) -> Path:
    """Resolve an output directory without allowing writes into the input tree."""

    input_path = Path(input_dir).expanduser().resolve()
    output_path = Path(output_dir).expanduser().resolve()
    if output_path == input_path or input_path in output_path.parents:
        raise ValueError("Output directory must not be the input directory or a child of it")
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path
