"""SCREENSHOT IDENTITY (mission responsibility 3)

SHA-256 content-addressed identity for FR24 screenshots. SHA-256 of the raw
image bytes is the canonical ``screenshot_id`` used throughout the pipeline and
persisted as ``screenshots.sha256`` (UNIQUE) in the database schema.

Pure functions only: no image decoding, no directory discovery, no I/O beyond an
explicit file read. Unit-testable with synthetic byte strings and tmp files.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Union

__all__ = [
    "sha256_of_bytes",
    "sha256_of_file",
    "screenshot_id_for_bytes",
    "screenshot_id_for_file",
]

_CHUNK = 1024 * 1024


def sha256_of_bytes(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of ``data``."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"expected bytes-like, got {type(data).__name__}")
    return hashlib.sha256(bytes(data)).hexdigest()


def sha256_of_file(path: Union[str, Path]) -> str:
    """Return the lowercase hex SHA-256 digest of the file at ``path``.

    Reads the file in chunks so identity computation does not depend on loading
    the whole image into memory. Raises ``FileNotFoundError`` if absent.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"screenshot not found: {p}")
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


# The screenshot_id IS the sha256 digest; these aliases document that contract
# at call sites (consistent with fr24.screenshot_inventory / FlightDatabase).
def screenshot_id_for_bytes(data: bytes) -> str:
    return sha256_of_bytes(data)


def screenshot_id_for_file(path: Union[str, Path]) -> str:
    return sha256_of_file(path)
