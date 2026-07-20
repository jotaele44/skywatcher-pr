"""Cursor-paginated query helpers for repository snapshots."""

from __future__ import annotations

from typing import Any, Iterable

from .pagination import CursorError, decode_cursor, encode_cursor
from .repositories.base import RepositorySnapshot
from .time import UTCValidationError, normalize_utc


class QueryValidationError(ValueError):
    pass


def parse_bbox(value: str | None) -> tuple[float, float, float, float] | None:
    if value in (None, ""):
        return None
    try:
        west, south, east, north = [float(part.strip()) for part in str(value).split(",")]
    except (TypeError, ValueError) as exc:
        raise QueryValidationError("bbox must be west,south,east,north") from exc
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= 90 and -90 <= north <= 90):
        raise QueryValidationError("bbox coordinates are outside valid geographic ranges")
    if west > east:
        raise QueryValidationError("antimeridian-crossing bbox is not supported in Phase 2")
    if south > north:
        raise QueryValidationError("bbox south must not exceed north")
    return west, south, east, north


def normalize_optional_utc(value: str | None, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return normalize_utc(value, field_name=field_name)
    except UTCValidationError as exc:
        raise QueryValidationError(str(exc)) from exc


def apply_bbox(rows: Iterable[dict[str, Any]], bbox: tuple[float, float, float, float] | None) -> list[dict[str, Any]]:
    if bbox is None:
        return list(rows)
    west, south, east, north = bbox
    output: list[dict[str, Any]] = []
    for row in rows:
        try:
            lon = float(row.get("lon"))
            lat = float(row.get("lat"))
        except (TypeError, ValueError):
            continue
        if west <= lon <= east and south <= lat <= north:
            output.append(row)
    return output


def apply_time_window(
    rows: Iterable[dict[str, Any]],
    *,
    field: str,
    from_utc: str | None,
    to_utc: str | None,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        value = row.get(field)
        if not value:
            continue
        if from_utc and str(value) < from_utc:
            continue
        if to_utc and str(value) > to_utc:
            continue
        output.append(row)
    return output


def paginate(
    snapshot: RepositorySnapshot,
    rows: Iterable[dict[str, Any]],
    *,
    sort_field: str,
    id_field: str,
    cursor: str | None,
    limit: int,
    filters: dict[str, Any],
    reverse: bool = False,
) -> dict[str, Any]:
    if limit < 1 or limit > 5000:
        raise QueryValidationError("limit must be between 1 and 5000")
    ordered = sorted(
        rows,
        key=lambda row: (str(row.get(sort_field) or ""), str(row.get(id_field) or row.get("id") or "")),
        reverse=reverse,
    )
    if cursor:
        try:
            payload = decode_cursor(cursor, filters=filters)
        except CursorError as exc:
            raise QueryValidationError(str(exc)) from exc
        marker = (str(payload["s"]), str(payload["id"]))
        if reverse:
            ordered = [row for row in ordered if (str(row.get(sort_field) or ""), str(row.get(id_field) or row.get("id") or "")) < marker]
        else:
            ordered = [row for row in ordered if (str(row.get(sort_field) or ""), str(row.get(id_field) or row.get("id") or "")) > marker]
    selected = ordered[: limit + 1]
    has_more = len(selected) > limit
    items = selected[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(
            sort_value=str(last.get(sort_field) or ""),
            stable_id=str(last.get(id_field) or last.get("id") or ""),
            filters=filters,
        )
    return {
        "items": items,
        "page": {
            "next_cursor": next_cursor,
            "has_more": has_more,
            "returned": len(items),
        },
        "availability": snapshot.as_status(),
    }
