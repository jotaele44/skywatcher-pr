from __future__ import annotations

from collections.abc import Iterable

from .crosswalk import class_ids

# Sourced from artifact_crosswalk_v1.json rather than restated here. This ordering used
# to sit alongside the taxonomy's per-class `priority` integer as if the two agreed;
# they cannot, because that integer is non-unique (A02/A11 both 7, A04/A09 both 8) and
# so cannot express a total order. The crosswalk's arbitration_rank is the real arbiter
# and is validated unique and dense at load. Same ordering as before.
PRIORITY = class_ids()


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
