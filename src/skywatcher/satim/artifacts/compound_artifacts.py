from __future__ import annotations

from typing import Iterable

PRIORITY = (
    "SATIM-A12",
    "SATIM-A11",
    "SATIM-A03",
    "SATIM-A07",
    "SATIM-A05",
    "SATIM-A06",
    "SATIM-A10",
    "SATIM-A01",
    "SATIM-A04",
    "SATIM-A09",
    "SATIM-A02",
    "SATIM-A08",
)


def normalize_classes(classes: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in classes:
        if value not in seen:
            seen.append(value)
    invalid = [v for v in seen if not v.startswith("SATIM-A")]
    if invalid:
        raise ValueError(f"invalid artifact class(es): {invalid}")
    return tuple(seen)


def select_primary(classes: Iterable[str]) -> tuple[str, tuple[str, ...]]:
    normalized = normalize_classes(classes)
    if not normalized:
        raise ValueError("at least one artifact class is required")
    primary = next((p for p in PRIORITY if p in normalized), normalized[0])
    return primary, tuple(v for v in normalized if v != primary)
