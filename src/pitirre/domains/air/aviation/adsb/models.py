"""
ADS-B feed — data models.

Plain dataclasses shared across providers and the sink. Kept dependency-free
(no pydantic), mirroring ``imagery/models.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class StateVector:
    """A single aircraft state observation (OpenSky ``/states/all`` record)."""

    icao24: str
    callsign: str | None
    origin_country: str | None
    time_position: int | None
    last_contact: int | None
    longitude: float | None
    latitude: float | None
    baro_altitude: float | None
    on_ground: bool
    velocity: float | None
    true_track: float | None
    vertical_rate: float | None
    geo_altitude: float | None
    squawk: str | None
    position_source: int | None
    provider: str = "opensky"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "icao24": self.icao24,
            "callsign": self.callsign,
            "origin_country": self.origin_country,
            "time_position": self.time_position,
            "last_contact": self.last_contact,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "baro_altitude": self.baro_altitude,
            "on_ground": self.on_ground,
            "velocity": self.velocity,
            "true_track": self.true_track,
            "vertical_rate": self.vertical_rate,
            "geo_altitude": self.geo_altitude,
            "squawk": self.squawk,
            "position_source": self.position_source,
        }
