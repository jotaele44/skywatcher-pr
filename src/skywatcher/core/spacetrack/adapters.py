"""Loss-minimizing normalization helpers for Space-Track rows.

Adapters preserve each raw input row verbatim under the raw key and add only
explicit normalized fields. They never merge records by name or discard
superseded assertions.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .control_plane import classify_decay_stage


def _raw_copy(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in row.items()}


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def normalize_satcat(row: dict[str, Any]) -> dict[str, Any]:
    raw = _raw_copy(row)
    return {
        "norad_cat_id": _string_or_none(raw.get("NORAD_CAT_ID")),
        "object_id": _string_or_none(raw.get("INTLDES") or raw.get("OBJECT_ID")),
        "object_name": _string_or_none(raw.get("SATNAME") or raw.get("OBJECT_NAME")),
        "country_code": _string_or_none(raw.get("COUNTRY") or raw.get("COUNTRY_CODE")),
        "launch_date": _string_or_none(raw.get("LAUNCH") or raw.get("LAUNCH_DATE")),
        "decay_date": _string_or_none(raw.get("DECAY") or raw.get("DECAY_DATE")),
        "comment_code": _string_or_none(raw.get("COMMENTCODE")),
        "debut": _string_or_none(raw.get("DEBUT")),
        "raw": raw,
    }


def normalize_gp(row: dict[str, Any]) -> dict[str, Any]:
    raw = _raw_copy(row)
    return {
        "gp_id": _string_or_none(raw.get("GP_ID")),
        "norad_cat_id": _string_or_none(raw.get("NORAD_CAT_ID")),
        "object_id": _string_or_none(raw.get("OBJECT_ID")),
        "object_name": _string_or_none(raw.get("OBJECT_NAME")),
        "epoch": _string_or_none(raw.get("EPOCH")),
        "creation_date": _string_or_none(raw.get("CREATION_DATE")),
        "mean_motion": raw.get("MEAN_MOTION"),
        "eccentricity": raw.get("ECCENTRICITY"),
        "inclination": raw.get("INCLINATION"),
        "ra_of_asc_node": raw.get("RA_OF_ASC_NODE"),
        "arg_of_pericenter": raw.get("ARG_OF_PERICENTER"),
        "mean_anomaly": raw.get("MEAN_ANOMALY"),
        "bstar": raw.get("BSTAR"),
        "mean_motion_dot": raw.get("MEAN_MOTION_DOT"),
        "mean_motion_ddot": raw.get("MEAN_MOTION_DDOT"),
        "ephemeris_type": raw.get("EPHEMERIS_TYPE"),
        "element_set_no": raw.get("ELEMENT_SET_NO"),
        "rev_at_epoch": raw.get("REV_AT_EPOCH"),
        "object_type": _string_or_none(raw.get("OBJECT_TYPE")),
        "country_code": _string_or_none(raw.get("COUNTRY_CODE")),
        "decay_date": _string_or_none(raw.get("DECAY_DATE")),
        "raw": raw,
    }


def normalize_decay(row: dict[str, Any]) -> dict[str, Any]:
    raw = _raw_copy(row)
    precedence = raw.get("PRECEDENCE")
    source = _string_or_none(raw.get("SOURCE"))
    return {
        "norad_cat_id": _string_or_none(raw.get("NORAD_CAT_ID")),
        "object_id": _string_or_none(raw.get("INTLDES") or raw.get("OBJECT_ID")),
        "object_name": _string_or_none(raw.get("SATNAME") or raw.get("OBJECT_NAME")),
        "message_epoch": _string_or_none(raw.get("MSG_EPOCH")),
        "decay_epoch": _string_or_none(raw.get("DECAY_EPOCH")),
        "source": source,
        "precedence": precedence,
        "decay_stage": classify_decay_stage(precedence),
        "assertion_role": (
            "PREDICTION"
            if source in {"60day_msg", "tip_msg"} or str(precedence) in {"3", "4"}
            else "HISTORICAL"
        ),
        "raw": raw,
    }


def normalize_tip(row: dict[str, Any]) -> dict[str, Any]:
    raw = _raw_copy(row)
    return {
        "tip_id": _string_or_none(raw.get("ID")),
        "norad_cat_id": _string_or_none(
            raw.get("NORAD_CAT_ID") or raw.get("OBJECT_NUMBER")
        ),
        "message_epoch": _string_or_none(raw.get("MSG_EPOCH")),
        "insert_epoch": _string_or_none(raw.get("INSERT_EPOCH")),
        "predicted_decay_epoch": _string_or_none(raw.get("DECAY_EPOCH")),
        "window_minutes": raw.get("WINDOW"),
        "predicted_10km_crossing_lat": raw.get("LAT"),
        "predicted_10km_crossing_lon_east": raw.get("LON"),
        "direction": _string_or_none(raw.get("DIRECTION")),
        "inclination": raw.get("INCL"),
        "high_interest": _string_or_none(raw.get("HIGH_INTEREST")),
        "next_report_hours": raw.get("NEXT_REPORT"),
        "raw": raw,
    }


def normalize_cdm(row: dict[str, Any]) -> dict[str, Any]:
    raw = _raw_copy(row)
    return {
        "created": _string_or_none(raw.get("CREATED")),
        "tca": _string_or_none(raw.get("TCA")),
        "raw": raw,
    }


def normalize_publicfile(row: dict[str, Any]) -> dict[str, Any]:
    raw = _raw_copy(row)
    return {
        "source": _string_or_none(raw.get("SOURCE") or raw.get("Source")),
        "type": _string_or_none(raw.get("TYPE") or raw.get("Type")),
        "generated_at": _string_or_none(raw.get("DATE") or raw.get("Date")),
        "link": _string_or_none(raw.get("LINK") or raw.get("Link")),
        "size": _string_or_none(raw.get("SIZE") or raw.get("Size")),
        "raw": raw,
    }


def normalize_catalog_change(row: dict[str, Any]) -> dict[str, Any]:
    raw = _raw_copy(row)
    return {
        "norad_cat_id": _string_or_none(raw.get("NORAD_CAT_ID")),
        "object_id": _string_or_none(raw.get("INTLDES")),
        "object_name": _string_or_none(raw.get("SATNAME")),
        "country_code": _string_or_none(raw.get("COUNTRY")),
        "launch_date": _string_or_none(raw.get("LAUNCH")),
        "decay_date": _string_or_none(raw.get("DECAY")),
        "raw": raw,
    }


def normalize_rows(source_id: str, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    dispatch = {
        "satcat": normalize_satcat,
        "satcat_debut": normalize_satcat,
        "satcat_change": normalize_catalog_change,
        "gp": normalize_gp,
        "gp_history": normalize_gp,
        "decay": normalize_decay,
        "decay_60day": normalize_decay,
        "tip": normalize_tip,
        "cdm_public": normalize_cdm,
        "publicfiles": normalize_publicfile,
        "curated_favorites": normalize_gp,
    }
    normalizer = dispatch.get(source_id)
    if normalizer is None:
        return [{"raw": _raw_copy(row)} for row in rows]
    return [normalizer(row) for row in rows]
