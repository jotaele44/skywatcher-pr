from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

PROTOCOL = "skywatcher-multisensor-replay-v1"
ALLOWED_SENSOR_TYPES = {
    "aircraft_observation",
    "provider_rendered_frame",
    "geomagnetic_timeseries",
    "weather_timeseries",
}


class ReplayError(ValueError):
    """Raised when replay inputs fail closed validation."""


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_utc(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReplayError("timestamp must be a non-empty string")
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ReplayError(f"invalid ISO-8601 timestamp: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReplayError("timestamp must include an explicit UTC offset")
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def validate_member_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReplayError("member path must be non-empty")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or normalized.startswith("/")
    ):
        raise ReplayError(f"unsafe member path: {value}")
    if any(part == "" for part in normalized.split("/")):
        raise ReplayError(f"non-canonical member path: {value}")
    return path.as_posix()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReplayError(f"JSON root must be an object: {path}")
    return value


def _validate_observation(
    value: dict[str, Any],
    *,
    source_types: dict[str, str],
    verified_members: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    required = {
        "observation_id",
        "source_id",
        "sensor_type",
        "event_time_utc",
        "payload",
    }
    missing = sorted(required - value.keys())
    if missing:
        raise ReplayError(f"observation missing fields: {missing}")

    source_id = str(value["source_id"])
    if source_id not in source_types:
        raise ReplayError(f"unknown source_id: {source_id}")

    sensor_type = str(value["sensor_type"])
    if sensor_type not in ALLOWED_SENSOR_TYPES:
        raise ReplayError(f"unsupported sensor_type: {sensor_type}")
    if source_types[source_id] != sensor_type:
        raise ReplayError(
            "source and observation sensor_type mismatch: "
            f"{source_id} declares {source_types[source_id]}, "
            f"observation declares {sensor_type}"
        )

    payload = value["payload"]
    if not isinstance(payload, dict):
        raise ReplayError("payload must be an object")

    if sensor_type == "aircraft_observation":
        if not {"lat", "lon"} <= payload.keys():
            raise ReplayError("aircraft payload requires lat and lon")
    elif sensor_type == "provider_rendered_frame":
        required_frame = {"member_path", "content_sha256", "product_type"}
        if not required_frame <= payload.keys():
            raise ReplayError(
                "frame payload requires member_path, content_sha256 and product_type"
            )
        member_path = validate_member_path(str(payload["member_path"]))
        member = verified_members.get(member_path)
        if member is None:
            raise ReplayError(
                f"provider frame references undeclared member: {member_path}"
            )
        if str(payload["content_sha256"]) != member["sha256"]:
            raise ReplayError(
                f"provider frame hash does not match verified member: {member_path}"
            )
        if payload["product_type"] != "provider_rendered_frame":
            raise ReplayError(
                "provider-rendered frame observation requires "
                "product_type=provider_rendered_frame"
            )
    elif (
        sensor_type in {"geomagnetic_timeseries", "weather_timeseries"}
        and not {"parameter", "value", "unit"} <= payload.keys()
    ):
        raise ReplayError(
            "timeseries payload requires parameter, value and unit"
        )

    result = dict(value)
    result["source_id"] = source_id
    result["sensor_type"] = sensor_type
    result["event_time_utc"] = normalize_utc(str(value["event_time_utc"]))
    result["payload"] = dict(payload)
    if sensor_type == "provider_rendered_frame":
        result["payload"]["member_path"] = validate_member_path(
            str(payload["member_path"])
        )
    return result


def _normalize_gaps(
    raw_gaps: Any,
    *,
    source_ids: set[str],
) -> list[dict[str, Any]]:
    if raw_gaps is None:
        return []
    if not isinstance(raw_gaps, list):
        raise ReplayError("gaps must be an array")

    gaps: list[dict[str, Any]] = []
    for gap in raw_gaps:
        if not isinstance(gap, dict):
            raise ReplayError("gap must be an object")
        source_id = gap.get("source_id")
        if source_id not in source_ids:
            raise ReplayError("invalid gap record")
        if "start_utc" not in gap or "end_utc" not in gap:
            raise ReplayError("gap requires start_utc and end_utc")
        start = normalize_utc(str(gap["start_utc"]))
        end = normalize_utc(str(gap["end_utc"]))
        if start >= end:
            raise ReplayError("gap start_utc must be before end_utc")
        gaps.append(
            {
                **gap,
                "source_id": str(source_id),
                "start_utc": start,
                "end_utc": end,
            }
        )

    gaps.sort(
        key=lambda item: (
            item["source_id"],
            item["start_utc"],
            item["end_utc"],
        )
    )
    last_end: dict[str, str] = {}
    for gap in gaps:
        prior_end = last_end.get(gap["source_id"])
        if prior_end is not None and gap["start_utc"] < prior_end:
            raise ReplayError(
                f"overlapping gaps for source_id: {gap['source_id']}"
            )
        last_end[gap["source_id"]] = gap["end_utc"]
    return sorted(
        gaps,
        key=lambda item: (item["start_utc"], item["source_id"]),
    )


def build_replay_receipt(
    bundle_root: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    root = bundle_root.resolve()
    manifest = _load_json(manifest_path)
    if manifest.get("protocol") != PROTOCOL:
        raise ReplayError(f"protocol must equal {PROTOCOL}")

    sources = manifest.get("sources")
    members = manifest.get("members")
    observations = manifest.get("observations")
    if (
        not isinstance(sources, list)
        or not isinstance(members, list)
        or not isinstance(observations, list)
    ):
        raise ReplayError("sources, members and observations must be arrays")

    source_types: dict[str, str] = {}
    normalized_sources: list[dict[str, Any]] = []
    for source in sources:
        if (
            not isinstance(source, dict)
            or not source.get("source_id")
            or not source.get("sensor_type")
        ):
            raise ReplayError("invalid source record")
        source_id = str(source["source_id"])
        sensor_type = str(source["sensor_type"])
        if source_id in source_types:
            raise ReplayError(f"duplicate source_id: {source_id}")
        if sensor_type not in ALLOWED_SENSOR_TYPES:
            raise ReplayError(
                f"unsupported source sensor_type: {sensor_type}"
            )
        source_types[source_id] = sensor_type
        normalized_sources.append(
            {**source, "source_id": source_id, "sensor_type": sensor_type}
        )

    normalized_members: list[dict[str, Any]] = []
    verified_members: dict[str, dict[str, Any]] = {}
    for member in members:
        if not isinstance(member, dict):
            raise ReplayError("member must be an object")
        rel = validate_member_path(str(member.get("path", "")))
        if rel in verified_members:
            raise ReplayError(f"duplicate member path: {rel}")
        expected = str(member.get("sha256", ""))
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ReplayError(f"member escapes bundle root: {rel}") from exc
        if not candidate.is_file():
            raise ReplayError(f"missing member: {rel}")
        actual = sha256_file(candidate)
        if expected != actual:
            raise ReplayError(f"content replacement detected for {rel}")
        verified = {
            "path": rel,
            "sha256": actual,
            "size": candidate.stat().st_size,
        }
        verified_members[rel] = verified
        normalized_members.append(verified)

    normalized_observations: list[dict[str, Any]] = []
    observation_ids: set[str] = set()
    for item in observations:
        if not isinstance(item, dict):
            raise ReplayError("every observation must be an object")
        observation_id = str(item.get("observation_id", ""))
        if not observation_id:
            raise ReplayError("observation_id must be non-empty")
        if observation_id in observation_ids:
            raise ReplayError(f"duplicate observation_id: {observation_id}")
        observation_ids.add(observation_id)
        normalized_observations.append(
            _validate_observation(
                item,
                source_types=source_types,
                verified_members=verified_members,
            )
        )

    normalized_observations.sort(
        key=lambda item: (
            item["event_time_utc"],
            item["observation_id"],
        )
    )
    timestamps = sorted(
        {item["event_time_utc"] for item in normalized_observations}
    )
    gaps = _normalize_gaps(
        manifest.get("gaps", []),
        source_ids=set(source_types),
    )

    body = {
        "protocol": PROTOCOL,
        "replay_id": manifest.get("replay_id"),
        "interpolation": "none",
        "timeline_policy": "union_observation_timestamps",
        "source_count": len(normalized_sources),
        "member_count": len(normalized_members),
        "observation_count": len(normalized_observations),
        "timestamp_count": len(timestamps),
        "sources": sorted(
            normalized_sources,
            key=lambda item: item["source_id"],
        ),
        "members": sorted(
            normalized_members,
            key=lambda item: item["path"],
        ),
        "observations": normalized_observations,
        "timestamps_utc": timestamps,
        "gaps": gaps,
    }
    body["content_digest"] = sha256_bytes(canonical_json(body))
    return body


def write_receipt(receipt: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json(receipt))
