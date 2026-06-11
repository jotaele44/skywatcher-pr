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

from integration.mbil import mbil_class, mbil_proximity_weight
from integration.kml_export import write_kml_for_geojson
from provenance_utils import geojson_feature_meta

PRODUCER_MODULE = "integration.ilap_airspace_bridge"

# EPSG code for the WGS-84 lat/lon CRS every artifact is emitted in (T7-65).
EPSG_CODE = 4326

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


def corridor_activity_label(connecting_flights: int) -> str:
    """Map a corridor's connecting-flight count to an operator-facing label (T7-59).

    Mirrors the POI review-priority banding so an analyst reads corridor and POI
    layers with one mental model.

      HIGH    ≥ 5 connecting flights — established, repeatedly-flown corridor
      MEDIUM  3–4                    — emerging corridor worth monitoring
      LOW     2                      — minimal evidence (below 2 is not emitted)
    """
    if connecting_flights >= 5:
        return "HIGH"
    if connecting_flights >= 3:
        return "MEDIUM"
    return "LOW"


class ILAPAirspaceBridge:
    def __init__(self, db_path: str, output_dir: str):
        self.db_path = db_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_all(self) -> Dict[str, Any]:
        # One emission timestamp shared by every feature in this run (T7-57).
        self._produced_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

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

    def _meta(self, source_artifact: str) -> Dict[str, str]:
        """Standardized GeoJSON Feature `_meta` block for this run (T7-57)."""
        return geojson_feature_meta(
            producer_module=PRODUCER_MODULE,
            source_artifact=source_artifact,
            produced_at=getattr(self, "_produced_at", None),
        )

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
            infra_align = 0.3  # placeholder; real impl would cross-ref infra layer
            hydro_utility = 0.2
            poi_mbil = mbil_class(center_lat, center_lon)
            mbil_proximity = mbil_proximity_weight(poi_mbil)

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
                    "mbil_class": poi_mbil,
                    "identity_note": IDENTITY_NOTE,
                    "_meta": self._meta("airspace_poi_candidates.geojson"),
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
                    "_meta": self._meta("airspace_ilap_candidates.geojson"),
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

                mid_lat = (lat1 + lat2) / 2.0
                mid_lon = (lon1 + lon2) / 2.0
                corridor_mbil = mbil_class(mid_lat, mid_lon)
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
                        "corridor_label": corridor_activity_label(corridor_flights),
                        "mbil_class": corridor_mbil,
                        "identity_note": IDENTITY_NOTE,
                        "_meta": self._meta("airspace_corridor_candidates.geojson"),
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
            # Explicit machine-readable EPSG alongside the OGC URN crs (T7-65).
            "epsg": EPSG_CODE,
            "features": features,
        }
        (self.output_dir / filename).write_text(json.dumps(geojson, indent=2))
        # Native KML sibling for Google Earth / QGIS (T7-58) — no ogr2ogr needed.
        kml_path = (self.output_dir / filename).with_suffix(".kml")
        write_kml_for_geojson(geojson, kml_path)

    def _safe_query(self, conn: sqlite3.Connection, sql: str) -> List[dict]:
        try:
            return [dict(r) for r in conn.execute(sql)]
        except Exception:
            return []
