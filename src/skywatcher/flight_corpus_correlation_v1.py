"""Synchronized trajectory correlation for historical FR24 flight corpora.

This module is deliberately descriptive. It measures synchronized geometry and
kinematics; it does not infer coordination, mission, targeting, or intent.

Key invariants:
- observations are matched only within a bounded timestamp delta;
- no long-gap interpolation is performed;
- duplicate flight manifestations are resolved by flight-id density, not name;
- missing geometry stays BLOCKED_GEOMETRY;
- shared-airport proximity and crossing trajectories remain distinct from
  sustained airborne co-route geometry.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable

EARTH_RADIUS_KM = 6371.0088
FLIGHT_ID_RE = re.compile(r"(?<![0-9a-f])([0-9a-f]{8})(?![0-9a-f])", re.IGNORECASE)

CLASSIFICATIONS = {
    "AIRBORNE_CO_ROUTE",
    "CROSSING_TRAJECTORIES",
    "SYNCHRONIZED_PROXIMITY",
    "SHARED_AIRPORT_OR_GROUND_PATTERN",
    "BRIEF_PROXIMITY",
    "OUT_OF_AREA_CONCURRENT",
    "TIME_ONLY",
    "UNRESOLVED_SYNC_SPARSE",
    "NO_SYNCHRONIZED_EVENT",
    "BLOCKED_GEOMETRY",
}

NON_INFERENCE = {
    "coordination": "UNKNOWN",
    "mission": "UNKNOWN",
    "targeting": "UNKNOWN",
    "intent": "UNKNOWN",
}


@dataclass(frozen=True)
class DetectorParameters:
    max_match_delta_seconds: float = 5.0
    max_duration_gap_seconds: float = 30.0
    brief_proximity_seconds: float = 60.0
    co_route_min_seconds: float = 120.0
    close_distance_km: float = 5.0
    out_of_area_distance_km: float = 50.0
    ground_altitude_ft: float = 500.0
    ground_fraction_threshold: float = 0.70
    co_route_heading_difference_deg: float = 30.0
    co_route_speed_difference_kt: float = 30.0
    crossing_heading_difference_deg: float = 60.0


@dataclass(frozen=True)
class TrackPoint:
    observed_at: datetime
    lat: float
    lon: float
    altitude_ft: float | None = None
    speed_kt: float | None = None
    heading_deg: float | None = None


@dataclass(frozen=True)
class Track:
    flight_id: str
    registration: str
    points: tuple[TrackPoint, ...]
    source_path: str = ""

    @property
    def start(self) -> datetime | None:
        return self.points[0].observed_at if self.points else None

    @property
    def end(self) -> datetime | None:
        return self.points[-1].observed_at if self.points else None


@dataclass(frozen=True)
class SynchronizedSample:
    left: TrackPoint
    right: TrackPoint
    delta_seconds: float
    distance_km: float
    altitude_difference_ft: float | None
    heading_difference_deg: float | None
    speed_difference_kt: float | None

    @property
    def observed_at(self) -> datetime:
        return min(self.left.observed_at, self.right.observed_at)


@dataclass(frozen=True)
class EventMetrics:
    synchronized_samples: int
    synchronized_span_seconds: float
    min_distance_km: float | None
    median_distance_km: float | None
    time_within_1km_seconds: float
    time_within_2km_seconds: float
    time_within_5km_seconds: float
    time_within_10km_seconds: float
    median_altitude_difference_ft: float | None
    median_heading_difference_deg: float | None
    median_speed_difference_kt: float | None
    groundlike_close_fraction: float | None
    classification: str
    coordination: str = "UNKNOWN"
    mission: str = "UNKNOWN"
    targeting: str = "UNKNOWN"
    intent: str = "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _float(value: Any) -> float | None:
    try:
        raw = _text(value)
        return float(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _timestamp(row: dict[str, Any]) -> datetime | None:
    for key in ("UTC", "utc", "timestamp_iso", "observed_at_utc", "observed_at"):
        raw = _text(row.get(key))
        if not raw:
            continue
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    for key in ("Timestamp", "timestamp", "time"):
        value = _float(row.get(key))
        if value is None:
            continue
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            continue
    return None


def _lat_lon(row: dict[str, Any]) -> tuple[float | None, float | None]:
    lat = _float(row.get("lat") or row.get("latitude"))
    lon = _float(row.get("lon") or row.get("lng") or row.get("longitude"))
    if lat is not None and lon is not None:
        return lat, lon

    raw = _text(
        row.get("Position")
        or row.get("position")
        or row.get("coordinates")
        or row.get("coordinate")
    )
    if not raw:
        return None, None
    parts = [part.strip() for part in raw.strip("()[]").split(",")]
    if len(parts) < 2:
        return None, None
    return _float(parts[0]), _float(parts[1])


def _flight_id(path: Path) -> str:
    match = FLIGHT_ID_RE.search(path.stem)
    return match.group(1).lower() if match else path.stem


def _registration(path: Path, rows: list[dict[str, str]]) -> str:
    aliases = ("Registration", "registration", "reg", "tail", "tail_number", "Callsign")
    for row in rows:
        for key in aliases:
            value = _text(row.get(key))
            if value:
                return value.upper()
    for part in reversed(path.parts):
        value = part.upper()
        if re.fullmatch(r"N[0-9A-Z-]{2,}", value):
            return value
    return "UNKNOWN"


def load_fr24_csv(path: str | Path) -> Track:
    """Load a single FR24-like track CSV without interpolating missing points."""

    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    points: list[TrackPoint] = []
    for row in rows:
        observed_at = _timestamp(row)
        lat, lon = _lat_lon(row)
        if observed_at is None or lat is None or lon is None:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        points.append(
            TrackPoint(
                observed_at=observed_at,
                lat=lat,
                lon=lon,
                altitude_ft=_float(
                    row.get("Altitude")
                    or row.get("altitude_ft")
                    or row.get("altitude")
                    or row.get("alt")
                ),
                speed_kt=_float(
                    row.get("Speed")
                    or row.get("speed_kt")
                    or row.get("groundspeed")
                    or row.get("speed")
                ),
                heading_deg=_float(
                    row.get("Direction")
                    or row.get("heading_deg")
                    or row.get("heading")
                    or row.get("track")
                ),
            )
        )
    points.sort(key=lambda point: point.observed_at)
    return Track(
        flight_id=_flight_id(source),
        registration=_registration(source, rows),
        points=tuple(points),
        source_path=str(source),
    )


def load_registration_tracks(root: str | Path, registration: str) -> list[Track]:
    """Load and density-dedupe all CSV manifestations for one registration."""

    target = registration.upper()
    candidates: dict[str, Track] = {}
    for path in sorted(Path(root).rglob("*.csv")):
        if target not in {part.upper() for part in path.parts} and target not in path.name.upper():
            continue
        track = load_fr24_csv(path)
        if track.registration not in {target, "UNKNOWN"}:
            continue
        current = candidates.get(track.flight_id)
        if current is None or len(track.points) > len(current.points):
            candidates[track.flight_id] = track
        elif (
            current is not None
            and len(track.points) == len(current.points)
            and track.source_path < current.source_path
        ):
            candidates[track.flight_id] = track
    return sorted(candidates.values(), key=lambda track: (track.start or datetime.min.replace(tzinfo=timezone.utc), track.flight_id))


def haversine_km(left: TrackPoint, right: TrackPoint) -> float:
    lat1 = math.radians(left.lat)
    lat2 = math.radians(right.lat)
    dlat = lat2 - lat1
    dlon = math.radians(right.lon - left.lon)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def circular_difference_deg(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return abs(left - right)


def temporal_overlap_seconds(left: Track, right: Track) -> float:
    if not left.points or not right.points:
        return 0.0
    start = max(left.points[0].observed_at, right.points[0].observed_at)
    end = min(left.points[-1].observed_at, right.points[-1].observed_at)
    return max(0.0, (end - start).total_seconds())


def synchronize_tracks(
    left: Track,
    right: Track,
    *,
    max_delta_seconds: float = 5.0,
) -> list[SynchronizedSample]:
    """Greedily match nearest unique source observations within a bounded delta."""

    if not left.points or not right.points:
        return []

    candidates: list[tuple[float, int, int]] = []
    j0 = 0
    right_points = right.points
    for i, point_left in enumerate(left.points):
        while (
            j0 < len(right_points)
            and (right_points[j0].observed_at - point_left.observed_at).total_seconds()
            < -max_delta_seconds
        ):
            j0 += 1
        j = j0
        while j < len(right_points):
            delta = (right_points[j].observed_at - point_left.observed_at).total_seconds()
            if delta > max_delta_seconds:
                break
            candidates.append((abs(delta), i, j))
            j += 1

    used_left: set[int] = set()
    used_right: set[int] = set()
    matches: list[SynchronizedSample] = []
    for delta, i, j in sorted(candidates, key=lambda row: (row[0], row[1], row[2])):
        if i in used_left or j in used_right:
            continue
        used_left.add(i)
        used_right.add(j)
        point_left = left.points[i]
        point_right = right.points[j]
        matches.append(
            SynchronizedSample(
                left=point_left,
                right=point_right,
                delta_seconds=delta,
                distance_km=haversine_km(point_left, point_right),
                altitude_difference_ft=_difference(point_left.altitude_ft, point_right.altitude_ft),
                heading_difference_deg=circular_difference_deg(
                    point_left.heading_deg,
                    point_right.heading_deg,
                ),
                speed_difference_kt=_difference(point_left.speed_kt, point_right.speed_kt),
            )
        )
    return sorted(matches, key=lambda sample: sample.observed_at)


def _duration_within(
    samples: list[SynchronizedSample],
    threshold_km: float,
    *,
    max_gap_seconds: float,
) -> float:
    total = 0.0
    for previous, current in zip(samples, samples[1:], strict=False):
        gap = (current.observed_at - previous.observed_at).total_seconds()
        if gap <= 0 or gap > max_gap_seconds:
            continue
        if previous.distance_km <= threshold_km and current.distance_km <= threshold_km:
            total += gap
    return total


def _median(values: Iterable[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return float(median(clean)) if clean else None


def classify_samples(
    samples: list[SynchronizedSample],
    parameters: DetectorParameters | None = None,
) -> EventMetrics:
    """Compute metrics and a descriptive, fail-closed geometry classification."""

    params = parameters or DetectorParameters()
    if not samples:
        return EventMetrics(
            synchronized_samples=0,
            synchronized_span_seconds=0.0,
            min_distance_km=None,
            median_distance_km=None,
            time_within_1km_seconds=0.0,
            time_within_2km_seconds=0.0,
            time_within_5km_seconds=0.0,
            time_within_10km_seconds=0.0,
            median_altitude_difference_ft=None,
            median_heading_difference_deg=None,
            median_speed_difference_kt=None,
            groundlike_close_fraction=None,
            classification="NO_SYNCHRONIZED_EVENT",
        )

    distances = [sample.distance_km for sample in samples]
    t1 = _duration_within(samples, 1.0, max_gap_seconds=params.max_duration_gap_seconds)
    t2 = _duration_within(samples, 2.0, max_gap_seconds=params.max_duration_gap_seconds)
    t5 = _duration_within(
        samples,
        params.close_distance_km,
        max_gap_seconds=params.max_duration_gap_seconds,
    )
    t10 = _duration_within(samples, 10.0, max_gap_seconds=params.max_duration_gap_seconds)
    close = [sample for sample in samples if sample.distance_km <= params.close_distance_km]
    groundlike = [
        sample
        for sample in close
        if sample.left.altitude_ft is not None
        and sample.right.altitude_ft is not None
        and sample.left.altitude_ft <= params.ground_altitude_ft
        and sample.right.altitude_ft <= params.ground_altitude_ft
    ]
    ground_fraction = len(groundlike) / len(close) if close else None
    heading_median = _median(sample.heading_difference_deg for sample in close)
    speed_median = _median(sample.speed_difference_kt for sample in close)

    if len(samples) < 3:
        classification = "UNRESOLVED_SYNC_SPARSE"
    elif min(distances) > params.out_of_area_distance_km:
        classification = "OUT_OF_AREA_CONCURRENT"
    elif t5 < params.brief_proximity_seconds:
        classification = "BRIEF_PROXIMITY" if min(distances) <= params.close_distance_km else "TIME_ONLY"
    elif ground_fraction is not None and ground_fraction >= params.ground_fraction_threshold:
        classification = "SHARED_AIRPORT_OR_GROUND_PATTERN"
    elif (
        t5 >= params.co_route_min_seconds
        and heading_median is not None
        and speed_median is not None
        and heading_median <= params.co_route_heading_difference_deg
        and speed_median <= params.co_route_speed_difference_kt
    ):
        classification = "AIRBORNE_CO_ROUTE"
    elif (
        heading_median is not None
        and heading_median >= params.crossing_heading_difference_deg
    ):
        classification = "CROSSING_TRAJECTORIES"
    else:
        classification = "SYNCHRONIZED_PROXIMITY"

    span = (
        (samples[-1].observed_at - samples[0].observed_at).total_seconds()
        if len(samples) > 1
        else 0.0
    )
    return EventMetrics(
        synchronized_samples=len(samples),
        synchronized_span_seconds=max(0.0, span),
        min_distance_km=min(distances),
        median_distance_km=float(median(distances)),
        time_within_1km_seconds=t1,
        time_within_2km_seconds=t2,
        time_within_5km_seconds=t5,
        time_within_10km_seconds=t10,
        median_altitude_difference_ft=_median(
            sample.altitude_difference_ft for sample in close
        ),
        median_heading_difference_deg=heading_median,
        median_speed_difference_kt=speed_median,
        groundlike_close_fraction=ground_fraction,
        classification=classification,
    )


def analyze_track_pair(
    left: Track,
    right: Track,
    parameters: DetectorParameters | None = None,
) -> dict[str, Any]:
    """Analyze one logical track pair while preserving non-inference fields."""

    params = parameters or DetectorParameters()
    if not left.points or not right.points:
        metrics = classify_samples([], params).to_dict()
        metrics["classification"] = "BLOCKED_GEOMETRY"
    elif temporal_overlap_seconds(left, right) <= 0:
        metrics = classify_samples([], params).to_dict()
    else:
        metrics = classify_samples(
            synchronize_tracks(
                left,
                right,
                max_delta_seconds=params.max_match_delta_seconds,
            ),
            params,
        ).to_dict()

    return {
        "left_registration": left.registration,
        "left_flight_id": left.flight_id,
        "right_registration": right.registration,
        "right_flight_id": right.flight_id,
        "temporal_overlap_seconds": temporal_overlap_seconds(left, right),
        **metrics,
    }


def analyze_registration_pair(
    left_tracks: list[Track],
    right_tracks: list[Track],
    parameters: DetectorParameters | None = None,
    *,
    minimum_overlap_seconds: float = 60.0,
) -> dict[str, Any]:
    """Analyze all temporally overlapping logical sorties for two registrations."""

    params = parameters or DetectorParameters()
    left_registration = left_tracks[0].registration if left_tracks else "UNKNOWN"
    right_registration = right_tracks[0].registration if right_tracks else "UNKNOWN"
    if not left_tracks or not right_tracks:
        return {
            "left_registration": left_registration,
            "right_registration": right_registration,
            "state": "BLOCKED_GEOMETRY",
            "events": [],
            "classification_counts": {"BLOCKED_GEOMETRY": 1},
            **NON_INFERENCE,
        }

    events: list[dict[str, Any]] = []
    for left in left_tracks:
        for right in right_tracks:
            overlap = temporal_overlap_seconds(left, right)
            if overlap < minimum_overlap_seconds:
                continue
            events.append(analyze_track_pair(left, right, params))

    counts: dict[str, int] = {}
    for event in events:
        key = str(event["classification"])
        counts[key] = counts.get(key, 0) + 1

    return {
        "left_registration": left_registration,
        "right_registration": right_registration,
        "state": "PROVISIONAL" if events else "NO_SYNCHRONIZED_EVENT",
        "events": events,
        "classification_counts": dict(sorted(counts.items())),
        **NON_INFERENCE,
    }
