"""DUPLICATE DETECTION (mission responsibility 12)

Two layers of duplicate detection:

* exact content duplicates by SHA-256 (see :mod:`skywatcher.fr24.screenshot_identity`);
* post-fusion candidate deduplication, wrapping ``fr24.fused_dedup`` (pure stdlib).

Both are testable without operational data (synthetic rows / synthetic bytes).
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from fr24.fused_dedup import (
    DEDUP_VERSION,
    dedup_key,
    dedupe_rows,
    row_quality,
)

from .screenshot_identity import sha256_of_bytes

__all__ = [
    "DEDUP_VERSION",
    "dedup_key",
    "dedupe_rows",
    "row_quality",
    "find_exact_duplicates",
]


def find_exact_duplicates(
    items: Iterable[Tuple[str, bytes]]
) -> Dict[str, List[str]]:
    """Group ``(name, data)`` items by SHA-256, returning only the groups that
    have more than one member (i.e. the exact duplicates).

    Pure/in-memory; used for content-address dedup of synthetic byte payloads in
    tests and for real screenshots at runtime.
    """
    by_hash: Dict[str, List[str]] = {}
    for name, data in items:
        by_hash.setdefault(sha256_of_bytes(data), []).append(name)
    return {h: names for h, names in by_hash.items() if len(names) > 1}
