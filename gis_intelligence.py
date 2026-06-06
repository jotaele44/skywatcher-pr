"""
PHASE 2: GIS INTELLIGENCE LAYER

Transforms:
  "Valid telemetry" → "Operational infrastructure intelligence"

Components:
1. Puerto Rico infrastructure graph (PREPA, ports, airports, restricted zones)
2. PostGIS migration path (production geospatial database)
3. Corridor analysis (power lines, maritime routes, SAR zones)
4. Heatmap generation (activity density, infrastructure proximity)
5. Anomaly detection (flights near restricted zones, unusual patterns)
"""

import sqlite3
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional
from enum import Enum
import json
from pathlib import Path
import math


# ============================================================================
# PUERTO RICO INFRASTRUCTURE DEFINITIONS
# ============================================================================

class InfrastructureType(Enum):
    AIRPORT = "airport"
    HELIPORT = "heliport"
    POWER_SUBSTATION = "power_substation"
    TRANSMISSION_LINE = "transmission_line"
    PORT = "port"
    COAST_GUARD_SECTOR = "coast_guard_sector"
    POLICE_BASE = "police_base"
    FEMA_FACILITY = "fema_facility"
    RESTRICTED_AIRSPACE = "restricted_airspace"
    MARITIME_ROUTE = "maritime_route"
    HURRICANE_SHELTER = "hurricane_shelter"
    FEDERAL_BUILDING = "federal_building"
    RADAR_INSTALLATION = "radar_installation"
    MARITIME_CHOKEPOINT = "maritime_chokepoint"


@dataclass
class InfrastructureFeature:
    feature_id: str
    name: str
    type: InfrastructureType
    latitude: float
    longitude: float
    radius_nm: float
    operational_notes: str = ""
    operator: str = ""
    sector: str = ""

    def distance_to_point(self, lat: float, lon: float) -> float:
        return haversine_nm(self.latitude, self.longitude, lat, lon)

    def is_within_radius(self, lat: float, lon: float) -> bool:
        return self.distance_to_point(lat, lon) <= self.radius_nm


class PuertoRicoInfrastructure:
    def __init__(self):
        self.features: Dict[str, InfrastructureFeature] = {}
        self._load_infrastructure()

    def _load_infrastructure(self):
        # AIRPORTS
        self.add_feature(InfrastructureFeature(
            feature_id="SJU",
            name="San Juan International (Luis Muñoz Marín)",
            type=InfrastructureType.AIRPORT,
            latitude=18.4386, longitude=-66.0010, radius_nm=5,
            operator="FAA",
            operational_notes="Primary commercial airport, Class B airspace"
        ))
        self.add_feature(InfrastructureFeature(
            feature_id="SIG",
            name="San Juan (Isla Grande)",
            type=InfrastructureType.HELIPORT,
            latitude=18.4519, longitude=-66.1198, radius_nm=2,
            operator="FAA",
            operational_notes="Helicopter/small aircraft base"
        ))
        self.add_feature(InfrastructureFeature(
            feature_id="BQN",
            name="Aguadilla (Ramey)",
            type=InfrastructureType.AIRPORT,
            latitude=18.5049, longitude=-67.1314, radius_nm=4,
            operator="FAA",
            operational_notes="Regional commercial airport"
        ))
        self.add_feature(InfrastructureFeature(
            feature_id="PSE",
            name="Ponce",
            type=InfrastructureType.AIRPORT,
            latitude=18.0075, longitude=-66.5627, radius_nm=3,
            operator="FAA",
            operational_notes="Regional airport"
        ))
        self.add_feature(InfrastructureFeature(
            feature_id="NRR",
            name="Ceiba (Roosevelt Roads)",
            type=InfrastructureType.AIRPORT,
            latitude=18.2536, longitude=-65.6362, radius_nm=4,
            operator="US Navy",
            operational_notes="Naval air station, former US military base"
        ))

        # POWER INFRASTRUCTURE (PREPA)
        self.add_feature(InfrastructureFeature(
            feature_id="PREPA_SOUTH_CORRIDOR",
            name="South Coast Transmission Corridor",
            type=InfrastructureType.TRANSMISSION_LINE,
            latitude=18.0, longitude=-66.5, radius_nm=15,
            operator="PREPA",
            operational_notes="Critical power transmission corridor, frequent inspection flights"
        ))
        self.add_feature(InfrastructureFeature(
            feature_id="PREPA_CENTRAL_GRID",
            name="Central Interior Distribution",
            type=InfrastructureType.TRANSMISSION_LINE,
            latitude=18.2, longitude=-66.3, radius_nm=20,
            operator="PREPA",
            operational_notes="Main distribution network, high inspection activity"
        ))
        self.add_feature(InfrastructureFeature(
            feature_id="PALO_SECO",
            name="Palo Seco Power Plant Area",
            type=InfrastructureType.POWER_SUBSTATION,
            latitude=18.0523, longitude=-67.0258, radius_nm=3,
            operator="PREPA",
            operational_notes="Major generation facility, critical infrastructure"
        ))

        # COAST GUARD SECTORS
        self.add_feature(InfrastructureFeature(
            feature_id="USCG_SJ",
            name="USCG San Juan Sector",
            type=InfrastructureType.COAST_GUARD_SECTOR,
            latitude=18.4386, longitude=-66.0010, radius_nm=50,
            operator="USCG",
            operational_notes="Maritime jurisdiction, active SAR operations"
        ))

        # MARITIME ROUTES
        self.add_feature(InfrastructureFeature(
            feature_id="MONA_PASSAGE",
            name="Mona Passage",
            type=InfrastructureType.MARITIME_ROUTE,
            latitude=18.85, longitude=-67.5, radius_nm=25,
            operator="USCG",
            operational_notes="High maritime traffic, dangerous crossing, frequent SAR"
        ))

        # PORTS
        self.add_feature(InfrastructureFeature(
            feature_id="PORT_SJ",
            name="Port of San Juan",
            type=InfrastructureType.PORT,
            latitude=18.4519, longitude=-66.1198, radius_nm=3,
            operator="PSA",
            operational_notes="Major container port, commercial shipping"
        ))

        # RESTRICTED AIRSPACE
        self.add_feature(InfrastructureFeature(
            feature_id="RESTRICTED_VIEQUES",
            name="Vieques Restricted Airspace",
            type=InfrastructureType.RESTRICTED_AIRSPACE,
            latitude=18.135, longitude=-65.435, radius_nm=10,
            operator="US Navy",
            operational_notes="Former bombing range, still restricted"
        ))

        # POLICE/LAW ENFORCEMENT
        self.add_feature(InfrastructureFeature(
            feature_id="FURA_BASE_SJ",
            name="FURA (Fuerzas Unidas de Rápida Acción) Base",
            type=InfrastructureType.POLICE_BASE,
            latitude=18.45, longitude=-66.05, radius_nm=2,
            operator="Puerto Rico Police",
            operational_notes="Tactical operations base, helicopter staging"
        ))

        # FEDERAL BUILDINGS
        self.add_feature(InfrastructureFeature(
            feature_id="FBI_SJ",
            name="FBI San Juan Field Office",
            type=InfrastructureType.FEDERAL_BUILDING,
            latitude=18.4133, longitude=-66.0594, radius_nm=1,
            sector="federal",
        ))
        self.add_feature(InfrastructureFeature(
            feature_id="CBP_SJ",
            name="DHS CBP Puerto Rico",
            type=InfrastructureType.FEDERAL_BUILDING,
            latitude=18.4386, longitude=-66.0010, radius_nm=2,
            sector="federal",
        ))
        self.add_feature(InfrastructureFeature(
            feature_id="FEMA_CARIBBEAN",
            name="FEMA Region II Caribbean",
            type=InfrastructureType.FEDERAL_BUILDING,
            latitude=18.4048, longitude=-66.0638, radius_nm=1,
            operator="FEMA",
            sector="federal",
        ))
        self.add_feature(InfrastructureFeature(
            feature_id="CBP_AMO_BQN",
            name="CBP Air and Marine Operations",
            type=InfrastructureType.FEDERAL_BUILDING,
            latitude=18.5049, longitude=-67.1314, radius_nm=2,
            sector="federal",
        ))
        self.add_feature(InfrastructureFeature(
            feature_id="USMS_SDPR",
            name="US Marshals SDPR",
            type=InfrastructureType.FEDERAL_BUILDING,
            latitude=18.4048, longitude=-66.0638, radius_nm=1,
            operator="US Marshals",
            sector="federal",
        ))

        # RADAR INSTALLATIONS
        self.add_feature(InfrastructureFeature(
            feature_id="TJUA",
            name="TJUA (San Juan/Cayey WSR-88D)",
            type=InfrastructureType.RADAR_INSTALLATION,
            latitude=18.1156, longitude=-66.0780, radius_nm=3,
            operator="NWS",
            sector="air",
        ))
        self.add_feature(InfrastructureFeature(
            feature_id="TJBQ",
            name="TJBQ (Aguadilla WSR-88D)",
            type=InfrastructureType.RADAR_INSTALLATION,
            latitude=18.4947, longitude=-67.1284, radius_nm=3,
            operator="NWS",
            sector="air",
        ))
        self.add_feature(InfrastructureFeature(
            feature_id="TISJ_TRACON",
            name="TISJ (San Juan Terminal Radar)",
            type=InfrastructureType.RADAR_INSTALLATION,
            latitude=18.4386, longitude=-66.0010, radius_nm=2,
            operator="FAA",
            sector="air",
        ))

        # MARITIME CHOKEPOINTS
        self.add_feature(InfrastructureFeature(
            feature_id="WINDWARD_PASSAGE",
            name="Windward Passage",
            type=InfrastructureType.MARITIME_CHOKEPOINT,
            latitude=19.8, longitude=-73.8, radius_nm=30,
            operator="USCG",
            sector="maritime",
        ))
        self.add_feature(InfrastructureFeature(
            feature_id="ANEGADA_PASSAGE",
            name="Anegada Passage",
            type=InfrastructureType.MARITIME_CHOKEPOINT,
            latitude=18.5, longitude=-63.8, radius_nm=25,
            operator="USCG",
            sector="maritime",
        ))
        self.add_feature(InfrastructureFeature(
            feature_id="MONA_CHOKEPOINT",
            name="Mona Chokepoint",
            type=InfrastructureType.MARITIME_CHOKEPOINT,
            latitude=18.05, longitude=-67.92, radius_nm=20,
            operator="USCG",
            sector="maritime",
        ))

    def add_feature(self, feature: InfrastructureFeature):
        self.features[feature.feature_id] = feature

    def get_nearby_features(self, lat: float, lon: float,
                            radius_nm: float = 5.0) -> List[InfrastructureFeature]:
        nearby = [f for f in self.features.values()
                  if f.distance_to_point(lat, lon) <= radius_nm]
        return sorted(nearby, key=lambda f: f.distance_to_point(lat, lon))

    def get_features_by_type(self, feature_type: InfrastructureType) -> List[InfrastructureFeature]:
        return [f for f in self.features.values() if f.type == feature_type]

    def get_features_by_operator(self, operator: str) -> List[InfrastructureFeature]:
        return [f for f in self.features.values() if f.operator == operator]

    def features_by_sector(self, sector: str) -> List[InfrastructureFeature]:
        """Return all features belonging to the named sector."""
        return [f for f in self.features.values() if getattr(f, "sector", "") == sector]


# ============================================================================
# CORRIDOR ANALYSIS
# ============================================================================

@dataclass
class FlightCorridor:
    corridor_id: str
    name: str
    start_point: Tuple[float, float]
    end_point: Tuple[float, float]
    width_nm: float
    purpose: str
    typical_operator: str
    activity_level: str
    associated_infrastructure: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def contains_point(self, lat: float, lon: float,
                       tolerance_nm: float = 1.0) -> bool:
        distance = point_to_line_distance(
            (lat, lon), self.start_point, self.end_point
        )
        return distance <= (self.width_nm / 2 + tolerance_nm)


class CorridorAnalyzer:
    def __init__(self, infrastructure: PuertoRicoInfrastructure):
        self.infrastructure = infrastructure
        self.corridors = self._define_corridors()

    def _define_corridors(self) -> List[FlightCorridor]:
        return [
            FlightCorridor(
                corridor_id="PREPA_SOUTH",
                name="South Coast Power Inspection Corridor",
                start_point=(18.0, -67.2), end_point=(18.0, -65.3),
                width_nm=5, purpose="power_line_inspection",
                typical_operator="PREPA", activity_level="high",
                associated_infrastructure=["PALO_SECO", "PREPA_SOUTH_CORRIDOR"]
            ),
            FlightCorridor(
                corridor_id="MONA_PATROL",
                name="Mona Passage Maritime Patrol",
                start_point=(18.5, -67.8), end_point=(18.5, -67.0),
                width_nm=15, purpose="maritime_patrol",
                typical_operator="USCG", activity_level="high",
                associated_infrastructure=["MONA_PASSAGE"]
            ),
            FlightCorridor(
                corridor_id="CENTRAL_GRID",
                name="Central Interior Power Grid Inspection",
                start_point=(18.5, -66.5), end_point=(18.0, -66.0),
                width_nm=8, purpose="power_line_inspection",
                typical_operator="PREPA", activity_level="high",
                associated_infrastructure=["PREPA_CENTRAL_GRID"]
            ),
        ]

    def find_corridors_for_flight(self, track_points: List[Dict]) -> List[FlightCorridor]:
        matching = []
        for corridor in self.corridors:
            in_corridor = sum(
                1 for p in track_points
                if corridor.contains_point(p["latitude"], p["longitude"])
            )
            if track_points and in_corridor > len(track_points) * 0.3:
                confidence = in_corridor / len(track_points)
                import dataclasses
                corridor = dataclasses.replace(corridor, confidence=round(confidence, 4))
                matching.append(corridor)
        return matching


# ============================================================================
# ANOMALY DETECTION
# ============================================================================

class AnomalyDetector:
    def __init__(self, infrastructure: PuertoRicoInfrastructure):
        self.infrastructure = infrastructure

    def detect_restricted_airspace_entry(self, track_points: List[Dict]) -> List[Dict]:
        violations = []
        restricted = self.infrastructure.get_features_by_type(
            InfrastructureType.RESTRICTED_AIRSPACE
        )
        for point in track_points:
            for zone in restricted:
                if zone.is_within_radius(point["latitude"], point["longitude"]):
                    violations.append({
                        "type": "restricted_airspace_entry",
                        "timestamp": point["timestamp"],
                        "latitude": point["latitude"],
                        "longitude": point["longitude"],
                        "infrastructure": zone.name,
                        "distance_nm": zone.distance_to_point(
                            point["latitude"], point["longitude"]
                        ),
                    })
        return violations

    def detect_infrastructure_proximity(self, track_points: List[Dict],
                                        radius_nm: float = 2.0) -> List[Dict]:
        proximities = []
        for point in track_points:
            nearby = self.infrastructure.get_nearby_features(
                point["latitude"], point["longitude"], radius_nm
            )
            for feature in nearby:
                proximities.append({
                    "timestamp": point["timestamp"],
                    "latitude": point["latitude"],
                    "longitude": point["longitude"],
                    "infrastructure": feature.name,
                    "type": feature.type.value,
                    "distance_nm": feature.distance_to_point(
                        point["latitude"], point["longitude"]
                    ),
                    "operator": feature.operator,
                })
        return proximities

    def detect_unusual_patterns(self, flight_data: Dict) -> List[Dict]:
        anomalies = []

        if flight_data.get("operator") == "PREPA":
            try:
                hour = int(flight_data.get("takeoff_time", "00:00:00")[11:13])
                if hour < 7 or hour > 18:
                    anomalies.append({
                        "type": "unusual_time",
                        "severity": "low",
                        "description": f"PREPA flight outside typical hours (hour {hour})",
                    })
            except (ValueError, IndexError):
                pass

        duration_hours = flight_data.get("flight_duration_minutes", 0) / 60
        if flight_data.get("aircraft_type") == "H125" and duration_hours > 8:
            anomalies.append({
                "type": "unusual_duration",
                "severity": "medium",
                "description": f"Unusually long flight duration: {duration_hours:.1f} hours",
            })

        if flight_data.get("num_screenshots", 0) > 100:
            anomalies.append({
                "type": "potential_clustering_error",
                "severity": "low",
                "description": "Very long sequence of screenshots for single aircraft",
            })

        return anomalies


# ============================================================================
# HEATMAP GENERATION
# ============================================================================

class HeatmapGenerator:
    def __init__(self, grid_size: float = 0.1):
        self.grid_size = grid_size
        self.grid: Dict[Tuple[float, float], float] = {}

    def add_point(self, lat: float, lon: float, weight: float = 1.0):
        lat_bucket = round(lat / self.grid_size) * self.grid_size
        lon_bucket = round(lon / self.grid_size) * self.grid_size
        key = (lat_bucket, lon_bucket)
        self.grid[key] = self.grid.get(key, 0) + weight

    def add_track(self, track_points: List[Dict], weight: float = 1.0):
        for point in track_points:
            self.add_point(point["latitude"], point["longitude"], weight)

    def get_geojson(self) -> Dict:
        features = []
        for (lat, lon), count in self.grid.items():
            intensity = min(1.0, count / 10.0)
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "intensity": intensity,
                    "count": count,
                    "color": intensity_to_color(intensity),
                },
            })
        return {"type": "FeatureCollection", "features": features}

    def to_kml(self) -> str:
        """Return KML string for Google Earth compatibility."""
        placemarks = []
        for (lat, lon), count in self.grid.items():
            intensity = min(count / max(self.grid.values(), default=1), 1.0)
            color = _kml_color(intensity)
            placemarks.append(
                f"  <Placemark>\n"
                f"    <name>{count} flights</name>\n"
                f"    <Style><IconStyle><color>{color}</color></IconStyle></Style>\n"
                f"    <Point><coordinates>{lon},{lat},0</coordinates></Point>\n"
                f"  </Placemark>"
            )
        body = "\n".join(placemarks)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
            '<Document>\n'
            f'{body}\n'
            '</Document>\n'
            '</kml>'
        )

    def get_density_stats(self) -> Dict:
        counts = list(self.grid.values())
        if not counts:
            return {}
        return {
            "total_cells": len(self.grid),
            "max_count": max(counts),
            "min_count": min(counts),
            "avg_count": sum(counts) / len(counts),
            "highest_activity_cell": max(self.grid.items(), key=lambda x: x[1]),
        }


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import radians, cos, sin, asin, sqrt
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return c * 3440.065


def point_to_line_distance(point: Tuple[float, float],
                           line_start: Tuple[float, float],
                           line_end: Tuple[float, float]) -> float:
    px, py = point
    x1, y1 = line_start
    x2, y2 = line_end
    denom = (x2 - x1) ** 2 + (y2 - y1) ** 2
    if denom == 0:
        return haversine_nm(py, px, y1, x1)
    t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / denom))
    closest_x = x1 + t * (x2 - x1)
    closest_y = y1 + t * (y2 - y1)
    return haversine_nm(py, px, closest_y, closest_x)


def intensity_to_color(intensity: float) -> str:
    if intensity < 0.33:
        r, g, b = 0, 255, 0
    elif intensity < 0.66:
        r, g, b = 255, 255, 0
    else:
        r, g, b = 255, 0, 0
    return f"rgb({r}, {g}, {b})"


def _kml_color(intensity: float) -> str:
    """Return KML ABGR hex color string for a 0-1 intensity value."""
    if intensity < 0.33:
        return "ff00ff00"  # green
    elif intensity < 0.66:
        return "ff00ffff"  # yellow
    return "ff0000ff"  # red (KML uses ABGR)


# ============================================================================
# PHASE 2 DATABASE INTEGRATION
# ============================================================================

class Phase2Database:
    def __init__(self, db_path: str = str(Path.home() / "flight_database.db")):
        self.db_path = db_path
        self.init_gis_tables()

    def init_gis_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS infrastructure_features (
                feature_id TEXT PRIMARY KEY,
                name TEXT,
                type TEXT,
                latitude REAL,
                longitude REAL,
                radius_nm REAL,
                operator TEXT,
                notes TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS flight_infrastructure (
                id INTEGER PRIMARY KEY,
                flight_id TEXT,
                infrastructure_id TEXT,
                closest_distance_nm REAL,
                min_altitude_during_proximity INTEGER,
                points_in_proximity INTEGER
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS flight_anomalies (
                anomaly_id INTEGER PRIMARY KEY AUTOINCREMENT,
                flight_id TEXT,
                anomaly_type TEXT,
                severity TEXT,
                description TEXT,
                detected_at TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS flight_corridors (
                corridor_id TEXT PRIMARY KEY,
                name TEXT,
                start_lat REAL,
                start_lon REAL,
                end_lat REAL,
                end_lon REAL,
                width_nm REAL,
                purpose TEXT,
                typical_operator TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS heatmap_cells (
                cell_id TEXT PRIMARY KEY,
                lat_center REAL,
                lon_center REAL,
                activity_count INTEGER,
                intensity REAL
            )
        ''')

        conn.commit()
        conn.close()

    def store_infrastructure(self, feature: InfrastructureFeature):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO infrastructure_features
            (feature_id, name, type, latitude, longitude, radius_nm, operator, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            feature.feature_id, feature.name, feature.type.value,
            feature.latitude, feature.longitude, feature.radius_nm,
            feature.operator, feature.operational_notes,
        ))
        conn.commit()
        conn.close()

    def store_anomalies(self, flight_id: str, anomalies: List[Dict]):
        from datetime import datetime
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        for anomaly in anomalies:
            cursor.execute('''
                INSERT INTO flight_anomalies
                (flight_id, anomaly_type, severity, description, detected_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                flight_id,
                anomaly.get("type", "unknown"),
                anomaly.get("severity", "unknown"),
                anomaly.get("description", ""),
                datetime.utcnow().isoformat(),
            ))
        conn.commit()
        conn.close()


if __name__ == "__main__":
    print("Phase 2 GIS Intelligence Layer loaded.")
    infra = PuertoRicoInfrastructure()
    print(f"  {len(infra.features)} infrastructure features defined")
