from __future__ import annotations

from typing import Any

from .core import normalize_utc, validate_member_path


def fr24_observation(*, observation_id: str, source_id: str, event_time: str, lat: float, lon: float, **fields: Any) -> dict[str, Any]:
    payload = {"lat": float(lat), "lon": float(lon), **fields}
    return {"observation_id": observation_id, "source_id": source_id, "sensor_type": "aircraft_observation", "event_time_utc": normalize_utc(event_time), "payload": payload}


def provider_frame(*, observation_id: str, source_id: str, event_time: str, member_path: str, content_sha256: str, product_type: str = "provider_rendered_frame", **fields: Any) -> dict[str, Any]:
    payload = {"member_path": validate_member_path(member_path), "content_sha256": content_sha256, "product_type": product_type, **fields}
    return {"observation_id": observation_id, "source_id": source_id, "sensor_type": "provider_rendered_frame", "event_time_utc": normalize_utc(event_time), "payload": payload}


def timeseries_observation(*, observation_id: str, source_id: str, sensor_type: str, event_time: str, parameter: str, value: float, unit: str, **fields: Any) -> dict[str, Any]:
    if sensor_type not in {"geomagnetic_timeseries", "weather_timeseries"}:
        raise ValueError("timeseries sensor_type is not admitted")
    payload = {"parameter": parameter, "value": float(value), "unit": unit, **fields}
    return {"observation_id": observation_id, "source_id": source_id, "sensor_type": sensor_type, "event_time_utc": normalize_utc(event_time), "payload": payload}
