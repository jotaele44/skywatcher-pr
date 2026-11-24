"""Deterministic Space-Track identity and current-view materialization.

Materialization never joins by name and never synthesizes orbital fields across
rows. Current records are selected as whole rows using source ordering evidence.
Conflicting stable identifiers remain unresolved and are preserved explicitly.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from .control_plane import logical_json_sha256
from .models import (
    CertificationState,
    ContradictionRecord,
    IdentityBinding,
    MaterializationResult,
    SpaceObjectView,
)
from .storage import SpaceTrackStore


def _text(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value)
    return rendered if rendered else None


def _catalog_key(norad_cat_id: str) -> str:
    return f"space-track:norad:{norad_cat_id}"


def _contradiction(category: str, key: str, observations: Iterable[str]) -> ContradictionRecord:
    ordered = tuple(sorted(set(str(value) for value in observations)))
    contradiction_id = logical_json_sha256(
        {"category": category, "key": key, "observations": ordered}
    )[:24]
    return ContradictionRecord(
        contradiction_id=contradiction_id,
        category=category,
        key=key,
        observations=ordered,
    )


def resolve_identity_bindings(
    rows: Iterable[dict[str, Any]],
) -> tuple[tuple[IdentityBinding, ...], tuple[ContradictionRecord, ...]]:
    material = list(rows)
    by_norad: dict[str, set[str]] = defaultdict(set)
    by_object: dict[str, set[str]] = defaultdict(set)

    for row in material:
        norad = _text(row.get("norad_cat_id"))
        object_id = _text(row.get("object_id"))
        if norad is not None and object_id is not None:
            by_norad[norad].add(object_id)
            by_object[object_id].add(norad)

    contradictions: list[ContradictionRecord] = []
    for norad, object_ids in sorted(by_norad.items()):
        if len(object_ids) > 1:
            contradictions.append(
                _contradiction("IDENTITY", f"NORAD_CAT_ID:{norad}", object_ids)
            )
    for object_id, norads in sorted(by_object.items()):
        if len(norads) > 1:
            contradictions.append(
                _contradiction("IDENTITY", f"OBJECT_ID:{object_id}", norads)
            )

    conflicted_norads = {
        item.key.split(":", 1)[1]
        for item in contradictions
        if item.key.startswith("NORAD_CAT_ID:")
    }
    conflicted_objects = {
        item.key.split(":", 1)[1]
        for item in contradictions
        if item.key.startswith("OBJECT_ID:")
    }

    seen: set[tuple[str | None, str | None]] = set()
    bindings: list[IdentityBinding] = []
    for row in material:
        norad = _text(row.get("norad_cat_id"))
        object_id = _text(row.get("object_id"))
        identity = (norad, object_id)
        if identity in seen:
            continue
        seen.add(identity)

        if norad is None and object_id is None:
            bindings.append(
                IdentityBinding(
                    catalog_key="unresolved",
                    norad_cat_id=None,
                    object_id=None,
                    state=CertificationState.UNRESOLVED,
                    evidence=(),
                )
            )
            continue

        if norad is None:
            bindings.append(
                IdentityBinding(
                    catalog_key=f"space-track:object-id:{object_id}",
                    norad_cat_id=None,
                    object_id=object_id,
                    state=CertificationState.PROVISIONAL,
                    evidence=("OBJECT_ID",),
                )
            )
            continue

        state = CertificationState.PASS if object_id is not None else CertificationState.PROVISIONAL
        if norad in conflicted_norads or (
            object_id is not None and object_id in conflicted_objects
        ):
            state = CertificationState.UNRESOLVED

        evidence = ("NORAD_CAT_ID", "OBJECT_ID") if object_id is not None else ("NORAD_CAT_ID",)
        bindings.append(
            IdentityBinding(
                catalog_key=_catalog_key(norad),
                norad_cat_id=norad,
                object_id=object_id,
                state=state,
                evidence=evidence,
            )
        )

    return tuple(bindings), tuple(contradictions)


def _numeric(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _select_satcat_current(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[ContradictionRecord]]:
    if not rows:
        return None, []
    ranked: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        file_id = _numeric(raw.get("FILE"))
        if file_id is not None:
            ranked.append((file_id, row))

    if not ranked:
        if len(rows) == 1:
            return rows[0], []
        return None, [
            _contradiction(
                "TIME",
                f"SATCAT_CURRENT:{_text(rows[0].get('norad_cat_id')) or 'UNKNOWN'}",
                ("multiple rows without FILE ordering evidence",),
            )
        ]

    top_file = max(value for value, _ in ranked)
    top_rows = [row for value, row in ranked if value == top_file]
    if len(top_rows) == 1:
        return top_rows[0], []

    unique = {logical_json_sha256(row) for row in top_rows}
    contradiction = _contradiction(
        "COUNT",
        f"SATCAT_FILE_TIE:{_text(top_rows[0].get('norad_cat_id')) or 'UNKNOWN'}:{top_file}",
        unique,
    )
    return top_rows[0] if len(unique) == 1 else None, [contradiction]


def _select_gp_current(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[ContradictionRecord]]:
    if not rows:
        return None, []

    def rank(row: dict[str, Any]) -> tuple[str, int]:
        creation = _text(row.get("creation_date")) or ""
        gp_id = _numeric(row.get("gp_id"))
        return creation, gp_id if gp_id is not None else -1

    ranked = sorted(rows, key=rank, reverse=True)
    top_rank = rank(ranked[0])
    top_rows = [row for row in ranked if rank(row) == top_rank]
    if len(top_rows) == 1:
        return top_rows[0], []

    unique = {logical_json_sha256(row) for row in top_rows}
    contradiction = _contradiction(
        "COUNT",
        f"GP_CURRENT_TIE:{_text(top_rows[0].get('norad_cat_id')) or 'UNKNOWN'}:{top_rank}",
        unique,
    )
    return top_rows[0] if len(unique) == 1 else None, [contradiction]


def materialize_space_objects(
    satcat_rows: Iterable[dict[str, Any]],
    gp_rows: Iterable[dict[str, Any]],
) -> MaterializationResult:
    satcat = list(satcat_rows)
    gp = list(gp_rows)
    combined = [*satcat, *gp]
    _, identity_contradictions = resolve_identity_bindings(combined)

    satcat_by_norad: dict[str, list[dict[str, Any]]] = defaultdict(list)
    gp_by_norad: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in satcat:
        norad = _text(row.get("norad_cat_id"))
        if norad is not None:
            satcat_by_norad[norad].append(row)
    for row in gp:
        norad = _text(row.get("norad_cat_id"))
        if norad is not None:
            gp_by_norad[norad].append(row)

    all_norads = sorted(set(satcat_by_norad) | set(gp_by_norad), key=lambda value: (len(value), value))
    contradictions = list(identity_contradictions)
    objects: list[SpaceObjectView] = []

    for norad in all_norads:
        sat_current, sat_conflicts = _select_satcat_current(satcat_by_norad[norad])
        gp_current, gp_conflicts = _select_gp_current(gp_by_norad[norad])
        contradictions.extend(sat_conflicts)
        contradictions.extend(gp_conflicts)

        rows = [*satcat_by_norad[norad], *gp_by_norad[norad]]
        object_ids = sorted(
            {
                value
                for row in rows
                if (value := _text(row.get("object_id"))) is not None
            }
        )
        aliases = tuple(
            sorted(
                {
                    value
                    for row in rows
                    if (value := _text(row.get("object_name"))) is not None
                }
            )
        )

        relevant_ids = tuple(
            item.contradiction_id
            for item in contradictions
            if (
                item.key.startswith(f"NORAD_CAT_ID:{norad}")
                or f":{norad}:" in item.key
                or item.key.endswith(f":{norad}")
                or (
                    item.key.startswith("OBJECT_ID:")
                    and item.key.split(":", 1)[1] in object_ids
                )
            )
        )
        if relevant_ids:
            identity_state = CertificationState.UNRESOLVED
        elif len(object_ids) == 1:
            identity_state = CertificationState.PASS
        else:
            identity_state = CertificationState.PROVISIONAL

        objects.append(
            SpaceObjectView(
                catalog_key=_catalog_key(norad),
                norad_cat_id=norad,
                object_id=object_ids[0] if len(object_ids) == 1 else None,
                identity_state=identity_state,
                satcat_row=sat_current,
                gp_row=gp_current,
                aliases=aliases,
                contradictions=relevant_ids,
            )
        )

    sat_ids = set(satcat_by_norad)
    gp_ids = set(gp_by_norad)
    return MaterializationResult(
        satcat_row_count=len(satcat),
        gp_row_count=len(gp),
        object_count=len(objects),
        unmatched_satcat=tuple(sorted(sat_ids - gp_ids)),
        unmatched_gp=tuple(sorted(gp_ids - sat_ids)),
        contradictions=tuple(contradictions),
        objects=tuple(objects),
    )



def materialize_stored_space_objects(
    store: SpaceTrackStore,
) -> tuple[MaterializationResult, str]:
    satcat_rows = [
        row
        for batch in store.load_normalized_batches("satcat")
        for row in batch.rows
    ]
    gp_rows = [
        row
        for batch in store.load_normalized_batches("gp")
        for row in batch.rows
    ]
    result = materialize_space_objects(satcat_rows, gp_rows)
    _, digest = store.freeze_materialization("space_objects", asdict(result))
    return result, digest
