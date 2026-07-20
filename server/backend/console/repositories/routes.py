"""Phase 2 routes repository adapter."""

from __future__ import annotations

from .flight_common import *  # noqa: F403
from .tracks import TrackPointRepository

class RouteSegmentRepository:
    name = "route_segments"

    def __init__(self, root: Path, track_repository: TrackPointRepository | None = None):
        self.root = root
        self.track_repository = track_repository or TrackPointRepository(root)

    def snapshot(self) -> RepositorySnapshot:
        track_snapshot = self.track_repository.snapshot()
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for point in track_snapshot.rows:
            flight_id = text(point.get("flight_id")) or "unassigned"
            segment_id = text(point.get("segment_id")) or "segment-0"
            groups[(flight_id, segment_id)].append(point)
        rows: list[dict[str, Any]] = []
        for (flight_id, segment_id), points in groups.items():
            points.sort(key=lambda point: (point["observed_at_utc"], point["track_point_id"]))
            first_point = points[0]
            route_id = f"{flight_id}::{segment_id}"
            row = {
                "id": route_id,
                "route_segment_id": route_id,
                "flight_id": None if flight_id == "unassigned" else flight_id,
                "segment_id": segment_id,
                "aircraft_id": first_point["aircraft_id"],
                "point_count": len(points),
                "first_seen_at_utc": points[0]["observed_at_utc"],
                "last_seen_at_utc": points[-1]["observed_at_utc"],
                "track_quality": "single_point" if len(points) == 1 else "sparse_evidence",
                "points": [
                    {
                        "track_point_id": point["track_point_id"],
                        "observed_at_utc": point["observed_at_utc"],
                        "lat": point["lat"],
                        "lon": point["lon"],
                        "measurement_status": point["measurement_status"],
                    }
                    for point in points
                ],
            }
            source_path = Path(first_point["provenance"]["artifact_path"])
            rows.append(
                attach_provenance(
                    row,
                    path=source_path,
                    adapter="RouteSegmentRepository:track_grouping",
                    source_record_id=route_id,
                    source_family=first_point["provenance"]["source_family"],
                    source_provider="skywatcher-route-segment-deriver",
                    source_method="derived_fusion",
                    data_rights="derived",
                    operational_mode=first_point["provenance"]["operational_mode"],
                    artifact_kind="derived_route_segment",
                    synthetic=all(bool(point.get("synthetic")) for point in points),
                )
            )
        return finalize_snapshot(
            self.name,
            rows,
            track_snapshot.artifacts,
            absent_reason=track_snapshot.reason,
            empty_reason="Track repositories contain no points that can form route segments.",
            warnings=track_snapshot.warnings,
            skipped_rows=track_snapshot.skipped_rows,
        )
