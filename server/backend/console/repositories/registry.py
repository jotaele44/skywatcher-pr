"""Repository registry and dashboard entity bindings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import RepositorySnapshot
from .capture_review import FR24CaptureRepository, ManualReviewRepository
from .flight_data import (
    AircraftStateRepository,
    AirportStateRepository,
    FlightSessionRepository,
    RouteSegmentRepository,
    TrackPointRepository,
)
from .profiles import AircraftProfileRepository

REPOSITORY_NAMES = (
    "fr24_captures",
    "manual_review_items",
    "aircraft_profiles",
    "track_points",
    "route_segments",
    "flight_sessions",
    "aircraft_states",
    "airport_operational_states",
)

ENTITY_REPOSITORY_MAP = {
    "FR24Captures": "fr24_captures",
    "ManualReviewItems": "manual_review_items",
    "AircraftProfiles": "aircraft_profiles",
    "RouteSegments": "route_segments",
}


class RepositoryRegistry:
    def __init__(self, root: Path):
        self.root = root
        self._cache: dict[str, RepositorySnapshot] = {}
        self._track_repository = TrackPointRepository(root)
        self._repositories = {
            "fr24_captures": FR24CaptureRepository(root),
            "manual_review_items": ManualReviewRepository(root),
            "aircraft_profiles": AircraftProfileRepository(root),
            "track_points": self._track_repository,
            "route_segments": RouteSegmentRepository(root, self._track_repository),
            "flight_sessions": FlightSessionRepository(root, self._track_repository),
            "aircraft_states": AircraftStateRepository(root, self._track_repository),
            "airport_operational_states": AirportStateRepository(root),
        }

    def snapshot(self, name: str) -> RepositorySnapshot:
        if name not in self._repositories:
            return RepositorySnapshot(
                repository=name,
                status="unavailable_no_adapter",
                reason="No Phase 2 repository adapter is registered for this collection.",
            )
        if name not in self._cache:
            self._cache[name] = self._repositories[name].snapshot()
        return self._cache[name]

    def entity_snapshot(self, entity_name: str) -> RepositorySnapshot | None:
        repository_name = ENTITY_REPOSITORY_MAP.get(entity_name)
        return self.snapshot(repository_name) if repository_name else None

    def statuses(self) -> list[dict[str, Any]]:
        return [self.snapshot(name).as_status() for name in REPOSITORY_NAMES]
