"""FastAPI router for Phase 2 repository and paginated console services."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .capabilities import build_capabilities
from .query import (
    QueryValidationError,
    apply_bbox,
    apply_time_window,
    normalize_optional_utc,
    paginate,
    parse_bbox,
)
from .repositories import RepositoryRegistry

ROOT = Path(__file__).resolve().parents[3]
router = APIRouter(prefix="/api/console", tags=["console"])


def _registry() -> RepositoryRegistry:
    return RepositoryRegistry(ROOT)


def _query_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/capabilities")
def get_console_capabilities() -> dict[str, Any]:
    """Return explicit support status for all 24 recorded capability groups."""

    return build_capabilities(ROOT)


@router.get("/repositories")
def get_repository_statuses() -> dict[str, Any]:
    registry = _registry()
    statuses = registry.statuses()
    return {
        "repository_count": len(statuses),
        "repositories": statuses,
        "policy": {
            "bounded_artifact_discovery": True,
            "read_only_source_artifacts": True,
            "row_level_provenance_required": True,
            "silent_empty_collections": False,
        },
    }


def _simple_page(
    repository_name: str,
    *,
    sort_field: str,
    id_field: str,
    cursor: str | None,
    limit: int,
    filters: dict[str, Any],
    predicate=None,
    reverse: bool = False,
) -> dict[str, Any]:
    snapshot = _registry().snapshot(repository_name)
    rows = list(snapshot.rows)
    if predicate:
        rows = [row for row in rows if predicate(row)]
    try:
        return paginate(
            snapshot,
            rows,
            sort_field=sort_field,
            id_field=id_field,
            cursor=cursor,
            limit=limit,
            filters=filters,
            reverse=reverse,
        )
    except QueryValidationError as exc:
        raise _query_error(exc) from exc


@router.get("/captures")
def list_captures(
    cursor: str | None = None,
    limit: int = Query(250, ge=1, le=5000),
    review_status: str | None = None,
    include_duplicates: bool = False,
    include_corrupt: bool = False,
    synthetic: bool | None = None,
) -> dict[str, Any]:
    filters = {
        "review_status": review_status,
        "include_duplicates": include_duplicates,
        "include_corrupt": include_corrupt,
        "synthetic": synthetic,
    }

    def predicate(row: dict[str, Any]) -> bool:
        if review_status and row.get("review_status") != review_status:
            return False
        if not include_duplicates and row.get("is_duplicate"):
            return False
        if not include_corrupt and row.get("is_corrupt"):
            return False
        if synthetic is not None and bool(row.get("synthetic")) != synthetic:
            return False
        return True

    return _simple_page(
        "fr24_captures",
        sort_field="scanned_at_utc",
        id_field="capture_id",
        cursor=cursor,
        limit=limit,
        filters=filters,
        predicate=predicate,
    )


@router.get("/review/items")
def list_review_items(
    cursor: str | None = None,
    limit: int = Query(250, ge=1, le=5000),
    queue_type: str | None = None,
    status: str | None = None,
    synthetic: bool | None = None,
) -> dict[str, Any]:
    filters = {"queue_type": queue_type, "status": status, "synthetic": synthetic}

    def predicate(row: dict[str, Any]) -> bool:
        return (
            (not queue_type or row.get("queue_type") == queue_type)
            and (not status or row.get("status") == status)
            and (synthetic is None or bool(row.get("synthetic")) == synthetic)
        )

    return _simple_page(
        "manual_review_items",
        sort_field="created_at_utc",
        id_field="item_id",
        cursor=cursor,
        limit=limit,
        filters=filters,
        predicate=predicate,
    )


@router.get("/aircraft/profiles")
def list_aircraft_profiles(
    cursor: str | None = None,
    limit: int = Query(250, ge=1, le=5000),
    callsign: str | None = None,
    registration: str | None = None,
    operator: str | None = None,
    synthetic: bool | None = None,
) -> dict[str, Any]:
    filters = {
        "callsign": callsign,
        "registration": registration,
        "operator": operator,
        "synthetic": synthetic,
    }

    def contains(value: Any, query: str | None) -> bool:
        return not query or query.lower() in str(value or "").lower()

    def predicate(row: dict[str, Any]) -> bool:
        return (
            contains(row.get("callsign"), callsign)
            and contains(row.get("registration"), registration)
            and contains(row.get("operator"), operator)
            and (synthetic is None or bool(row.get("synthetic")) == synthetic)
        )

    return _simple_page(
        "aircraft_profiles",
        sort_field="aircraft_id",
        id_field="profile_id",
        cursor=cursor,
        limit=limit,
        filters=filters,
        predicate=predicate,
    )


@router.get("/aircraft/states")
def list_aircraft_states(
    bbox: str | None = None,
    at: str | None = None,
    source_method: list[str] | None = Query(None),
    synthetic: bool | None = None,
    cursor: str | None = None,
    limit: int = Query(1000, ge=1, le=5000),
) -> dict[str, Any]:
    try:
        parsed_bbox = parse_bbox(bbox)
        at_utc = normalize_optional_utc(at, "at")
    except QueryValidationError as exc:
        raise _query_error(exc) from exc
    filters = {
        "bbox": bbox,
        "at": at_utc,
        "source_method": sorted(source_method or []),
        "synthetic": synthetic,
    }
    snapshot = _registry().snapshot("aircraft_states")
    rows = apply_bbox(snapshot.rows, parsed_bbox)
    rows = [
        row
        for row in rows
        if (synthetic is None or bool(row.get("synthetic")) == synthetic)
        and (not source_method or row.get("provenance", {}).get("source_method") in source_method)
        and (not at_utc or str(row.get("observed_at_utc")) <= at_utc)
    ]
    try:
        return paginate(
            snapshot,
            rows,
            sort_field="observed_at_utc",
            id_field="state_id",
            cursor=cursor,
            limit=limit,
            filters=filters,
            reverse=True,
        )
    except QueryValidationError as exc:
        raise _query_error(exc) from exc


@router.get("/flights")
def list_flights(
    from_time: str | None = Query(None, alias="from"),
    to_time: str | None = Query(None, alias="to"),
    aircraft_id: str | None = None,
    callsign: str | None = None,
    registration: str | None = None,
    synthetic: bool | None = None,
    cursor: str | None = None,
    limit: int = Query(250, ge=1, le=5000),
) -> dict[str, Any]:
    try:
        from_utc = normalize_optional_utc(from_time, "from")
        to_utc = normalize_optional_utc(to_time, "to")
    except QueryValidationError as exc:
        raise _query_error(exc) from exc
    filters = {
        "from": from_utc,
        "to": to_utc,
        "aircraft_id": aircraft_id,
        "callsign": callsign,
        "registration": registration,
        "synthetic": synthetic,
    }
    snapshot = _registry().snapshot("flight_sessions")
    rows = apply_time_window(
        snapshot.rows,
        field="first_seen_at_utc",
        from_utc=from_utc,
        to_utc=to_utc,
    )
    rows = [
        row
        for row in rows
        if (not aircraft_id or row.get("aircraft_id") == aircraft_id)
        and (not callsign or callsign.lower() in str(row.get("callsign") or "").lower())
        and (not registration or registration.lower() in str(row.get("registration") or "").lower())
        and (synthetic is None or bool(row.get("synthetic")) == synthetic)
    ]
    try:
        return paginate(
            snapshot,
            rows,
            sort_field="first_seen_at_utc",
            id_field="flight_id",
            cursor=cursor,
            limit=limit,
            filters=filters,
            reverse=True,
        )
    except QueryValidationError as exc:
        raise _query_error(exc) from exc


@router.get("/flights/{flight_id}")
def get_flight(flight_id: str) -> dict[str, Any]:
    snapshot = _registry().snapshot("flight_sessions")
    for row in snapshot.rows:
        if str(row.get("flight_id")) == flight_id:
            return {"item": row, "availability": snapshot.as_status()}
    if snapshot.status.startswith("unavailable"):
        raise HTTPException(status_code=503, detail=snapshot.as_status())
    raise HTTPException(status_code=404, detail=f"flight not found: {flight_id}")


@router.get("/flights/{flight_id}/track")
def get_flight_track(
    flight_id: str,
    from_time: str | None = Query(None, alias="from"),
    to_time: str | None = Query(None, alias="to"),
    include_interpolated: bool = False,
    cursor: str | None = None,
    limit: int = Query(1000, ge=1, le=5000),
) -> dict[str, Any]:
    try:
        from_utc = normalize_optional_utc(from_time, "from")
        to_utc = normalize_optional_utc(to_time, "to")
    except QueryValidationError as exc:
        raise _query_error(exc) from exc
    filters = {
        "flight_id": flight_id,
        "from": from_utc,
        "to": to_utc,
        "include_interpolated": include_interpolated,
    }
    snapshot = _registry().snapshot("track_points")
    rows = [row for row in snapshot.rows if str(row.get("flight_id") or "") == flight_id]
    rows = apply_time_window(rows, field="observed_at_utc", from_utc=from_utc, to_utc=to_utc)
    if not include_interpolated:
        rows = [row for row in rows if row.get("measurement_status") != "interpolated_for_display"]
    try:
        page = paginate(
            snapshot,
            rows,
            sort_field="observed_at_utc",
            id_field="track_point_id",
            cursor=cursor,
            limit=limit,
            filters=filters,
        )
    except QueryValidationError as exc:
        raise _query_error(exc) from exc
    page["disclosure"] = {
        "continuous_tracking": bool(rows) and all(row.get("measurement_status") == "measured" for row in rows),
        "interpolation_applied": any(row.get("measurement_status") == "interpolated_for_display" for row in page["items"]),
        "message": (
            "Screenshot-derived and legacy route points are evidence observations, not continuous operational tracking."
            if any(row.get("measurement_status") == "derived_from_screenshot" for row in rows)
            else "Track points retain their source measurement status."
        ),
    }
    return page


@router.get("/routes")
def list_routes(
    flight_id: str | None = None,
    aircraft_id: str | None = None,
    synthetic: bool | None = None,
    cursor: str | None = None,
    limit: int = Query(250, ge=1, le=5000),
) -> dict[str, Any]:
    filters = {"flight_id": flight_id, "aircraft_id": aircraft_id, "synthetic": synthetic}

    def predicate(row: dict[str, Any]) -> bool:
        return (
            (not flight_id or row.get("flight_id") == flight_id)
            and (not aircraft_id or row.get("aircraft_id") == aircraft_id)
            and (synthetic is None or bool(row.get("synthetic")) == synthetic)
        )

    return _simple_page(
        "route_segments",
        sort_field="first_seen_at_utc",
        id_field="route_segment_id",
        cursor=cursor,
        limit=limit,
        filters=filters,
        predicate=predicate,
        reverse=True,
    )


@router.get("/airports/{airport_id}/operations")
def get_airport_operations(
    airport_id: str,
    from_time: str | None = Query(None, alias="from"),
    to_time: str | None = Query(None, alias="to"),
    cursor: str | None = None,
    limit: int = Query(250, ge=1, le=5000),
) -> dict[str, Any]:
    try:
        from_utc = normalize_optional_utc(from_time, "from")
        to_utc = normalize_optional_utc(to_time, "to")
    except QueryValidationError as exc:
        raise _query_error(exc) from exc
    filters = {"airport_id": airport_id, "from": from_utc, "to": to_utc}
    snapshot = _registry().snapshot("airport_operational_states")
    rows = [row for row in snapshot.rows if str(row.get("airport_id")) == airport_id]
    rows = apply_time_window(rows, field="observed_at_utc", from_utc=from_utc, to_utc=to_utc)
    try:
        return paginate(
            snapshot,
            rows,
            sort_field="observed_at_utc",
            id_field="airport_state_id",
            cursor=cursor,
            limit=limit,
            filters=filters,
            reverse=True,
        )
    except QueryValidationError as exc:
        raise _query_error(exc) from exc
