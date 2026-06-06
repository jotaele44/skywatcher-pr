"""
ILAP AIRSPACE BRIDGE
Exports POI candidates, ILAP corridor candidates, and corridor pair candidates
as GeoJSON for ingestion into the ILAP/Spiderweb airspace intelligence system.
"""

import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from gis_intelligence import PuertoRicoInfrastructure, haversine_nm
    _INFRA = PuertoRicoInfrastructure()
except Exception:
    _INFRA = None


def _infra_align_score(center_lat: float, center_lon: float) -> float:
    """Return infrastructure alignment score in [0, 1] for a POI centroid.

    Scores based on proximity to the nearest known PR infrastructure feature:
      ≤2 nm  → 1.0 (directly over/adjacent to feature)
      ≤5 nm  → 0.75
      ≤10 nm → 0.50
      ≤20 nm → 0.25
      >20 nm → 0.10 (baseline; no known infrastructure nearby)
    Falls back to 0.3 when gis_intelligence is unavailable.
    """
    if _INFRA is None:
        return 0.3
    min_dist = min(
        (f.distance_to_point(center_lat, center_lon) for f in _INFRA.features.values()),
        default=999.0,
    )
    if min_dist <= 2:
        return 1.0
    if min_dist <= 5:
        return 0.75
    if min_dist <= 10:
        return 0.50
    if min_dist <= 20:
        return 0.25
    return 0.10


IDENTITY_NOTE = (
    "N/A or weak aircraft identity may increase review priority "
    "but is not standalone evidence"
)

CONFIDENCE_WEIGHTS = {
    "recurrence": 0.30,
    "loiter": 0.25,
    "infra_align": 0.20,
    "hydro_utility": 0.15,
    "mbil_proximity": 0.10,
}

GRID_DEG = 0.05  # ~5 km grid cell size


def _hydro_utility_score(center_lat: float, center_lon: float) -> float:
    """Return hydro-utility score for a POI centroid using GEBCO depth data.

    Attempts to use GEBCO bathymetry at the track centroid.  Falls back to the
    historical baseline (0.2) when the GEBCO module is unavailable or has no
    data covering the requested point.
    """
    try:
        from gebco.io import GebcoIO
        gio = GebcoIO()
        if not gio.validate_bounds(center_lat - 0.01, center_lat + 0.01,
                                   center_lon - 0.01, center_lon + 0.01):
            return 0.2
        depth_m = gio.depth_at(center_lat, center_lon)
        if depth_m is None:
            return 0.2
        # Shallow coastal water (< 200 m) → higher utility; deep ocean → lower
        if abs(depth_m) < 50:
            return 0.9
        if abs(depth_m) < 200:
            return 0.6
        if abs(depth_m) < 1000:
            return 0.4
        return 0.2
    except Exception:
        return 0.2


class ILAPAirspaceBridge:
    def __init__(self, db_path: str, output_dir: str):
        self.db_path = db_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_all(self) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        track_pts = self._safe_query(conn, "SELECT * FROM track_points")
        flights = self._safe_query(conn, "SELECT * FROM flights")
        conn.close()

        poi_features = self._build_poi_candidates(track_pts)
        ilap_features = self._build_ilap_candidates(flights, track_pts)
        corridor_features = self._build_corridor_candidates(poi_features, flights)

        counts = {
            "airspace_poi_candidates.geojson": len(poi_features),
            "airspace_ilap_candidates.geojson": len(ilap_features),
            "airspace_corridor_candidates.geojson": len(corridor_features),
        }

        self._write_geojson("airspace_poi_candidates.geojson", poi_features)
        self._write_geojson("airspace_ilap_candidates.geojson", ilap_features)
        self._write_geojson("airspace_corridor_candidates.geojson", corridor_features)

        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "output_dir": str(self.output_dir),
            "files": counts,
        }

    # ------------------------------------------------------------------ POI

    def _build_poi_candidates(self, track_pts: List[dict]) -> List[dict]:
        # Cluster by 0.05° grid cell
        cells: Dict[Tuple[int, int], List[dict]] = defaultdict(list)
        for tp in track_pts:
            lat = tp.get("latitude") or 0.0
            lon = tp.get("longitude") or 0.0
            if lat == 0.0 and lon == 0.0:
                continue
            cell = (int(lat / GRID_DEG), int(lon / GRID_DEG))
            cells[cell].append(tp)

        features = []
        for cell, points in cells.items():
            if len(points) < 3:
                continue
            flight_ids = {tp.get("flight_id") for tp in points if tp.get("flight_id")}
            if len(flight_ids) < 2:
                continue

            lats = [tp.get("latitude") or 0.0 for tp in points]
            lons = [tp.get("longitude") or 0.0 for tp in points]
            center_lat = sum(lats) / len(lats)
            center_lon = sum(lons) / len(lons)

            recurrence = min(1.0, len(flight_ids) / 10.0)
            loiter = self._loiter_score(points)
            infra_align = _infra_align_score(center_lat, center_lon)
            hydro_utility = _hydro_utility_score(center_lat, center_lon)
            mbil_proximity = 0.1

            overall = (
                CONFIDENCE_WEIGHTS["recurrence"] * recurrence
                + CONFIDENCE_WEIGHTS["loiter"] * loiter
                + CONFIDENCE_WEIGHTS["infra_align"] * infra_align
                + CONFIDENCE_WEIGHTS["hydro_utility"] * hydro_utility
                + CONFIDENCE_WEIGHTS["mbil_proximity"] * mbil_proximity
            )

            if overall >= 0.7:
                priority = "HIGH"
            elif overall >= 0.4:
                priority = "MEDIUM"
            else:
                priority = "LOW"

            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [center_lon, center_lat]},
                "properties": {
                    "lat": round(center_lat, 5),
                    "lon": round(center_lon, 5),
                    "flight_count": len(flight_ids),
                    "point_count": len(points),
                    "recurrence_score": round(recurrence, 4),
                    "loiter_score": round(loiter, 4),
                    "infra_alignment_score": round(infra_align, 4),
                    "overall_confidence": round(overall, 4),
                    "review_priority": priority,
                    "identity_note": IDENTITY_NOTE,
                },
            })

        return features

    def _loiter_score(self, points: List[dict]) -> float:
        if len(points) < 2:
            return 0.0
        speeds = [tp.get("ground_speed_mph") or 0 for tp in points]
        low_speed = sum(1 for s in speeds if s < 50)
        return min(1.0, low_speed / len(points))

    # ----------------------------------------------------------------- ILAP

    def _build_ilap_candidates(self, flights: List[dict], track_pts: List[dict]) -> List[dict]:
        features = []
        tp_by_flight: Dict[str, list] = defaultdict(list)
        for tp in track_pts:
            fid = tp.get("flight_id")
            if fid:
                tp_by_flight[fid].append(tp)

        for f in flights:
            fid = f.get("flight_id", "")
            corridor_score = f.get("corridor_alignment_score") or 0.0
            if corridor_score <= 0.3 and not tp_by_flight.get(fid):
                continue

            pts = tp_by_flight.get(fid, [])
            if len(pts) >= 2:
                coords = [[tp.get("longitude", 0.0), tp.get("latitude", 0.0)] for tp in pts]
            else:
                olat = f.get("origin_lat")
                olon = f.get("origin_lon")
                dlat = f.get("dest_lat")
                dlon = f.get("dest_lon")
                if olat and olon and dlat and dlon:
                    coords = [[olon, olat], [dlon, dlat]]
                else:
                    continue

            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "flight_id": fid,
                    "callsign": f.get("callsign", ""),
                    "mission_type": f.get("mission_type", ""),
                    "corridor_alignment_score": corridor_score,
                    "identity_note": IDENTITY_NOTE,
                },
            })

        return features

    # --------------------------------------------------------------- corridors

    def _build_corridor_candidates(self, poi_features: List[dict],
                                   flights: List[dict]) -> List[dict]:
        features = []
        n = len(poi_features)
        if n < 2:
            return features

        # Build origin→dest flight index
        route_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        for f in flights:
            o = f.get("origin_airport", "")
            d = f.get("destination_airport", "")
            if o and d and o != d:
                key = (min(o, d), max(o, d))
                route_counts[key] += 1

        # Pair POI candidates that have ≥ 2 connecting flights
        for i in range(n):
            for j in range(i + 1, n):
                p1 = poi_features[i]["properties"]
                p2 = poi_features[j]["properties"]
                lat1, lon1 = p1["lat"], p1["lon"]
                lat2, lon2 = p2["lat"], p2["lon"]

                corridor_flights = sum(
                    1 for f in flights
                    if self._near(f.get("origin_lat"), f.get("origin_lon"), lat1, lon1, 0.1)
                    and self._near(f.get("dest_lat"), f.get("dest_lon"), lat2, lon2, 0.1)
                ) + sum(
                    1 for f in flights
                    if self._near(f.get("origin_lat"), f.get("origin_lon"), lat2, lon2, 0.1)
                    and self._near(f.get("dest_lat"), f.get("dest_lon"), lat1, lon1, 0.1)
                )

                if corridor_flights < 2:
                    continue

                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[lon1, lat1], [lon2, lat2]],
                    },
                    "properties": {
                        "poi_a": f"{lat1},{lon1}",
                        "poi_b": f"{lat2},{lon2}",
                        "connecting_flights": corridor_flights,
                        "identity_note": IDENTITY_NOTE,
                    },
                })

        return features

    # ----------------------------------------------------------------- helpers

    def _near(self, lat, lon, ref_lat: float, ref_lon: float, thresh_deg: float) -> bool:
        if lat is None or lon is None:
            return False
        return abs(lat - ref_lat) <= thresh_deg and abs(lon - ref_lon) <= thresh_deg

    def _write_geojson(self, filename: str, features: List[dict]):
        geojson = {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4326"}},
            "features": features,
        }
        (self.output_dir / filename).write_text(json.dumps(geojson, indent=2))

    def _safe_query(self, conn: sqlite3.Connection, sql: str) -> List[dict]:
        try:
            return [dict(r) for r in conn.execute(sql)]
        except Exception:
            return []


def poi_to_earthgpt_context(poi_feature: dict) -> dict:
    """Convert an ILAP POI GeoJSON feature to an EarthGPT TileContext dict.

    Parameters
    ----------
    poi_feature:
        A GeoJSON Feature from ``airspace_poi_candidates.geojson``.

    Returns
    -------
    dict compatible with ``TileContext.from_row()`` / ``ContextNormalizer.validate()``.
    """
    props = poi_feature.get("properties", {})
    lat = props.get("lat", 0.0)
    lon = props.get("lon", 0.0)
    return {
        "x":            0,
        "y":            0,
        "zoom":         15,
        "tile_type":    "land",
        "coast_weight": 1.0,
        "water_weight": 1.0,
        "poi_lat":      lat,
        "poi_lon":      lon,
        "overall_confidence": props.get("overall_confidence", 0.0),
        "review_priority":    props.get("review_priority", "LOW"),
    }
