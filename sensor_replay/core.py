from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

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
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


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
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_member_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReplayError("member path must be non-empty")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or normalized.startswith("/"):
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


def _validate_observation(value: dict[str, Any], *, source_ids: set[str]) -> dict[str, Any]:
    required = {"observation_id", "source_id", "sensor_type", "event_time_utc", "payload"}
    missing = sorted(required - value.keys())
    if missing:
        raise ReplayError(f"observation missing fields: {missing}")
    if value["source_id"] not in source_ids:
        raise ReplayError(f"unknown source_id: {value['source_id']}")
    if value["sensor_type"] not in ALLOWED_SENSOR_TYPES:
        raise ReplayError(f"unsupported sensor_type: {value['sensor_type']}")
    payload = value["payload"]
    if not isinstance(payload, dict):
        raise ReplayError("payload must be an object")
    sensor_type = value["sensor_type"]
    if sensor_type == "aircraft_observation" and not {"lat", "lon"} <= payload.keys():
        raise ReplayError("aircraft payload requires lat and lon")
    if sensor_type == "provider_rendered_frame" and not {"member_path", "content_sha256", "product_type"} <= payload.keys():
        raise ReplayError("frame payload requires member_path, content_sha256 and product_type")
    if sensor_type in {"geomagnetic_timeseries", "weather_timeseries"} and not {"parameter", "value", "unit"} <= payload.keys():
        raise ReplayError("timeseries payload requires parameter, value and unit")
    result = dict(value)
    result["event_time_utc"] = normalize_utc(str(value["event_time_utc"]))
    return result


def build_replay_receipt(bundle_root: Path, manifest_path: Path) -> dict[str, Any]:
    root = bundle_root.resolve()
    manifest = _load_json(manifest_path)
    if manifest.get("protocol") != PROTOCOL:
        raise ReplayError(f"protocol must equal {PROTOCOL}")
    sources = manifest.get("sources")
    members = manifest.get("members")
    observations = manifest.get("observations")
    if not isinstance(sources, list) or not isinstance(members, list) or not isinstance(observations, list):
        raise ReplayError("sources, members and observations must be arrays")

    source_ids: set[str] = set()
    normalized_sources: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict) or not source.get("source_id") or not source.get("sensor_type"):
            raise ReplayError("invalid source record")
        if source["source_id"] in source_ids:
            raise ReplayError(f"duplicate source_id: {source['source_id']}")
        if source["sensor_type"] not in ALLOWED_SENSOR_TYPES:
            raise ReplayError(f"unsupported source sensor_type: {source['sensor_type']}")
        source_ids.add(source["source_id"])
        normalized_sources.append(dict(source))

    normalized_members: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for member in members:
        if not isinstance(member, dict):
            raise ReplayError("member must be an object")
        rel = validate_member_path(str(member.get("path", "")))
        if rel in seen_paths:
            raise ReplayError(f"duplicate member path: {rel}")
        seen_paths.add(rel)
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
        normalized_members.append({"path": rel, "sha256": actual, "size": candidate.stat().st_size})

    normalized_observations = [_validate_observation(item, source_ids=source_ids) for item in observations if isinstance(item, dict)]
    if len(normalized_observations) != len(observations):
        raise ReplayError("every observation must be an object")
    normalized_observations.sort(key=lambda item: (item["event_time_utc"], item["observation_id"]))
    timestamps = sorted({item["event_time_utc"] for item in normalized_observations})

    gaps: list[dict[str, Any]] = []
    for gap in manifest.get("gaps", []):
        if not isinstance(gap, dict) or gap.get("source_id") not in source_ids:
            raise ReplayError("invalid gap record")
        gaps.append({**gap, "start_utc": normalize_utc(str(gap["start_utc"])), "end_utc": normalize_utc(str(gap["end_utc"]))})
    gaps.sort(key=lambda item: (item["start_utc"], item["source_id"]))

    body = {
        "protocol": PROTOCOL,
        "replay_id": manifest.get("replay_id"),
        "interpolation": "none",
        "timeline_policy": "union_observation_timestamps",
        "source_count": len(normalized_sources),
        "member_count": len(normalized_members),
        "observation_count": len(normalized_observations),
        "timestamp_count": len(timestamps),
        "sources": sorted(normalized_sources, key=lambda item: item["source_id"]),
        "members": sorted(normalized_members, key=lambda item: item["path"]),
        "observations": normalized_observations,
        "timestamps_utc": timestamps,
        "gaps": gaps,
    }
    body["content_digest"] = sha256_bytes(canonical_json(body))
    return body


def write_receipt(receipt: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json(receipt))
