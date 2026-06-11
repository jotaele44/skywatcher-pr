"""
PHASE 3: MISSION INFERENCE ENGINE

Transforms: "Geographic patterns + validated telemetry"
       → "Operational objectives with probability scores"

Three components:

1. MultiFactorMissionScorer
   Weighted model scoring each flight against known mission profiles.

2. BehavioralClusterer
   K-means clustering on flight feature vectors.

3. MarkovChainPredictor
   Learns state transition probabilities from historical flights.
"""

import sqlite3
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from enum import Enum
from datetime import datetime
from collections import defaultdict


# ============================================================================
# MISSION PROFILES
# ============================================================================

class MissionType(Enum):
    POWER_INSPECTION   = "Power Line Inspection"
    EMERGENCY_RESPONSE = "Emergency Response"
    SEARCH_AND_RESCUE  = "Search & Rescue"
    MEDICAL_TRANSPORT  = "Medical/Emergency Transport"
    LAW_ENFORCEMENT    = "Law Enforcement"
    DISASTER_RESPONSE  = "Disaster Response / Damage Assessment"
    MARITIME_PATROL    = "Maritime Patrol"
    PRIVATE_CHARTER    = "Private Charter"
    TRAINING           = "Training Flight"
    UTILITY_WORK       = "Utility / Infrastructure Work"
    ANTI_SMUGGLING     = "Anti-Smuggling / Interdiction"
    UNKNOWN            = "Unknown"


@dataclass
class MissionProfile:
    mission_type: MissionType
    typical_altitude_min: float
    typical_altitude_max: float
    typical_speed_min: float
    typical_speed_max: float
    typical_duration_min: float
    typical_duration_max: float
    hover_behavior: float
    repetitive_route: float
    linear_corridor: float
    search_pattern: float
    infrastructure_types: List[str]
    operating_hours: str
    typical_operators: List[str]
    typical_altitude_variance: float
    typical_terrain: str


MISSION_PROFILES: Dict[MissionType, MissionProfile] = {

    MissionType.POWER_INSPECTION: MissionProfile(
        mission_type=MissionType.POWER_INSPECTION,
        typical_altitude_min=500, typical_altitude_max=3000,
        typical_speed_min=40, typical_speed_max=120,
        typical_duration_min=90, typical_duration_max=480,
        hover_behavior=0.6, repetitive_route=0.7,
        linear_corridor=0.9, search_pattern=0.1,
        infrastructure_types=["transmission_line", "power_substation"],
        operating_hours="daytime",
        typical_operators=["PREPA", "N5854Z"],
        typical_altitude_variance=0.4, typical_terrain="all",
    ),

    MissionType.SEARCH_AND_RESCUE: MissionProfile(
        mission_type=MissionType.SEARCH_AND_RESCUE,
        typical_altitude_min=200, typical_altitude_max=5000,
        typical_speed_min=20, typical_speed_max=150,
        typical_duration_min=60, typical_duration_max=360,
        hover_behavior=0.8, repetitive_route=0.3,
        linear_corridor=0.2, search_pattern=0.9,
        infrastructure_types=["coast_guard_sector", "maritime_route"],
        operating_hours="24/7",
        typical_operators=["USCG", "C6062"],
        typical_altitude_variance=0.9, typical_terrain="coastal",
    ),

    MissionType.LAW_ENFORCEMENT: MissionProfile(
        mission_type=MissionType.LAW_ENFORCEMENT,
        typical_altitude_min=300, typical_altitude_max=4000,
        typical_speed_min=30, typical_speed_max=140,
        typical_duration_min=30, typical_duration_max=240,
        hover_behavior=0.7, repetitive_route=0.4,
        linear_corridor=0.3, search_pattern=0.6,
        infrastructure_types=["police_base"],
        operating_hours="24/7",
        typical_operators=["FURA", "N767PD"],
        typical_altitude_variance=0.7, typical_terrain="urban",
    ),

    MissionType.EMERGENCY_RESPONSE: MissionProfile(
        mission_type=MissionType.EMERGENCY_RESPONSE,
        typical_altitude_min=500, typical_altitude_max=8000,
        typical_speed_min=100, typical_speed_max=160,
        typical_duration_min=10, typical_duration_max=120,
        hover_behavior=0.2, repetitive_route=0.1,
        linear_corridor=0.8, search_pattern=0.1,
        infrastructure_types=["airport", "heliport"],
        operating_hours="24/7",
        typical_operators=["USCG", "FURA", "PREPA"],
        typical_altitude_variance=0.3, typical_terrain="all",
    ),

    MissionType.MARITIME_PATROL: MissionProfile(
        mission_type=MissionType.MARITIME_PATROL,
        typical_altitude_min=300, typical_altitude_max=8000,
        typical_speed_min=100, typical_speed_max=160,
        typical_duration_min=120, typical_duration_max=360,
        hover_behavior=0.2, repetitive_route=0.6,
        linear_corridor=0.7, search_pattern=0.5,
        infrastructure_types=["maritime_route", "port", "coast_guard_sector"],
        operating_hours="24/7",
        typical_operators=["USCG", "C6062"],
        typical_altitude_variance=0.5, typical_terrain="coastal",
    ),

    MissionType.PRIVATE_CHARTER: MissionProfile(
        mission_type=MissionType.PRIVATE_CHARTER,
        typical_altitude_min=2000, typical_altitude_max=8000,
        typical_speed_min=90, typical_speed_max=160,
        typical_duration_min=20, typical_duration_max=120,
        hover_behavior=0.0, repetitive_route=0.2,
        linear_corridor=0.8, search_pattern=0.0,
        infrastructure_types=["airport"],
        operating_hours="daytime",
        typical_operators=["N684JB"],
        typical_altitude_variance=0.2, typical_terrain="all",
    ),

    MissionType.DISASTER_RESPONSE: MissionProfile(
        mission_type=MissionType.DISASTER_RESPONSE,
        typical_altitude_min=200, typical_altitude_max=5000,
        typical_speed_min=30, typical_speed_max=140,
        typical_duration_min=120, typical_duration_max=600,
        hover_behavior=0.7, repetitive_route=0.5,
        linear_corridor=0.5, search_pattern=0.6,
        infrastructure_types=["power_substation", "transmission_line", "fema_facility"],
        operating_hours="24/7",
        typical_operators=["PREPA", "USCG", "FURA"],
        typical_altitude_variance=0.6, typical_terrain="all",
    ),
}


# ============================================================================
# MULTI-FACTOR MISSION SCORER
# ============================================================================

@dataclass
class MissionScore:
    mission_type: MissionType
    total_score: float
    signal_scores: Dict[str, float]
    confidence_level: str
    explanation: List[str]


class MultiFactorMissionScorer:
    SIGNAL_WEIGHTS = {
        "corridor_alignment":       0.20,
        "infrastructure_proximity": 0.18,
        "altitude_profile":         0.15,
        "hover_behavior":           0.12,
        "operator_identity":        0.10,
        "repeat_frequency":         0.08,
        "time_pattern":             0.08,
        "speed_profile":            0.06,
        "duration_profile":         0.03,
    }

    def __init__(self, db_path: str = str(Path.home() / "flight_database.db")):
        self.db_path = db_path

    def score_flight(self, flight: Dict, track_points: List[Dict],
                     nearby_infrastructure: List[Dict],
                     matching_corridors: List[str]) -> List[MissionScore]:
        scores = [
            self._score_against_profile(
                flight, track_points, nearby_infrastructure,
                matching_corridors, profile
            )
            for profile in MISSION_PROFILES.values()
        ]
        return sorted(scores, key=lambda s: s.total_score, reverse=True)

    def _score_against_profile(self, flight: Dict, track_points: List[Dict],
                               nearby_infra: List[Dict], corridors: List[str],
                               profile: MissionProfile) -> MissionScore:
        signals = {}
        explanation = []

        # Corridor alignment
        if profile.linear_corridor > 0.7 and corridors:
            signals["corridor_alignment"] = 0.9
            explanation.append("Flight follows known corridor")
        elif profile.search_pattern > 0.7 and not corridors:
            signals["corridor_alignment"] = 0.8
            explanation.append("No corridor — consistent with search pattern")
        else:
            signals["corridor_alignment"] = 0.4

        # Infrastructure proximity
        relevant = [i for i in nearby_infra if i.get("type") in profile.infrastructure_types]
        if relevant:
            closest = min(relevant, key=lambda x: x.get("distance_nm", 99))
            dist = closest.get("distance_nm", 99)
            signals["infrastructure_proximity"] = max(0.0, 1.0 - dist / 10.0)
            explanation.append(f"Near {closest.get('infrastructure', '?')} ({dist:.1f} nm)")
        else:
            signals["infrastructure_proximity"] = 0.0

        # Altitude profile
        alt = flight.get("max_altitude_ft", 0) or 0
        if profile.typical_altitude_min <= alt <= profile.typical_altitude_max:
            signals["altitude_profile"] = 1.0
        elif alt < profile.typical_altitude_min:
            signals["altitude_profile"] = max(0.0, 1.0 - (profile.typical_altitude_min - alt) / 2000.0)
        else:
            signals["altitude_profile"] = max(0.0, 1.0 - (alt - profile.typical_altitude_max) / 3000.0)

        # Hover behavior
        hover_score = self._detect_hover_score(track_points)
        diff = abs(hover_score - profile.hover_behavior)
        signals["hover_behavior"] = 0.9 if diff < 0.2 else (0.6 if diff < 0.4 else 0.2)

        # Operator identity
        callsign = flight.get("callsign", "")
        operator = flight.get("operator", "")
        signals["operator_identity"] = 0.3
        for known in profile.typical_operators:
            if known in callsign or known in operator:
                signals["operator_identity"] = 1.0
                explanation.append(f"Known operator match: {known}")
                break

        # Repeat frequency
        signals["repeat_frequency"] = self._get_repeat_frequency(
            callsign, profile.mission_type
        )

        # Time pattern
        signals["time_pattern"] = self._score_time_pattern(
            flight.get("takeoff_time", ""), profile.operating_hours
        )

        # Speed profile
        speed = flight.get("avg_speed_mph", 0) or 0
        if profile.typical_speed_min <= speed <= profile.typical_speed_max:
            signals["speed_profile"] = 1.0
        elif speed < profile.typical_speed_min:
            signals["speed_profile"] = max(0.0, 1.0 - (profile.typical_speed_min - speed) / 50.0)
        else:
            signals["speed_profile"] = max(0.0, 1.0 - (speed - profile.typical_speed_max) / 50.0)

        # Duration profile
        duration = flight.get("flight_duration_minutes", 0) or 0
        if profile.typical_duration_min <= duration <= profile.typical_duration_max:
            signals["duration_profile"] = 1.0
        elif duration < profile.typical_duration_min:
            signals["duration_profile"] = max(0.0, 1.0 - (profile.typical_duration_min - duration) / 60.0)
        else:
            signals["duration_profile"] = max(0.0, 1.0 - (duration - profile.typical_duration_max) / 120.0)

        total = sum(signals[s] * w for s, w in self.SIGNAL_WEIGHTS.items())
        confidence = "HIGH" if total >= 0.75 else ("MEDIUM" if total >= 0.50 else "LOW")

        return MissionScore(
            mission_type=profile.mission_type,
            total_score=total,
            signal_scores=signals,
            confidence_level=confidence,
            explanation=explanation,
        )

    def _detect_hover_score(self, track_points: List[Dict]) -> float:
        if not track_points:
            return 0.0
        hover = sum(1 for p in track_points if float(p.get("ground_speed_mph") or 99) < 20)
        return hover / len(track_points)

    def _get_repeat_frequency(self, callsign: str, mission_type: MissionType) -> float:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM flights WHERE callsign = ? AND mission_type = ?",
                (callsign, mission_type.value)
            )
            count = cursor.fetchone()[0]
            conn.close()
            return min(1.0, count / 10.0)
        except Exception:
            return 0.0

    def _score_time_pattern(self, takeoff_time: str, operating_hours: str) -> float:
        if operating_hours == "24/7":
            return 0.8
        try:
            dt = datetime.fromisoformat(takeoff_time)
            hour = dt.hour
        except Exception:
            return 0.5
        if operating_hours == "daytime":
            if 7 <= hour <= 18:
                return 1.0
            elif 6 <= hour <= 20:
                return 0.6
            return 0.1
        return 0.5


# ============================================================================
# BEHAVIORAL CLUSTERER
# ============================================================================

@dataclass
class FlightFeatureVector:
    flight_id: str
    callsign: str
    altitude_norm: float
    speed_norm: float
    duration_norm: float
    altitude_variance_norm: float
    hover_proportion: float
    path_linearity: float
    coverage_area_norm: float
    coastal_proportion: float
    infrastructure_score: float


class BehavioralClusterer:
    def __init__(self, n_clusters: int = 6):
        self.n_clusters = n_clusters
        self.centroids: List[List[float]] = []
        self.cluster_labels: Dict[str, int] = {}
        self.cluster_profiles: Dict[int, Dict] = {}

    def extract_feature_vector(self, flight: Dict,
                               track_points: List[Dict]) -> FlightFeatureVector:
        altitudes = [p.get("altitude_ft") or 0 for p in track_points]
        max_alt = max(altitudes) if altitudes else 0
        alt_range = (max(altitudes) - min(altitudes)) if len(altitudes) > 1 else 0

        speeds = [p.get("ground_speed_mph") or 0 for p in track_points]
        avg_speed = sum(speeds) / len(speeds) if speeds else 0
        hover_prop = sum(1 for s in speeds if s < 20) / len(speeds) if speeds else 0

        linearity = self._compute_linearity(track_points)
        coverage = self._compute_coverage_norm(track_points)

        coastal = 0.0
        if track_points:
            coastal = sum(
                1 for p in track_points
                if (p.get("latitude") or 0) > 18.35 or (p.get("latitude") or 0) < 18.05
            ) / len(track_points)

        return FlightFeatureVector(
            flight_id=flight.get("flight_id", ""),
            callsign=flight.get("callsign", ""),
            altitude_norm=min(1.0, max_alt / 10000.0),
            speed_norm=min(1.0, avg_speed / 180.0),
            duration_norm=min(1.0, (flight.get("flight_duration_minutes") or 0) / 480.0),
            altitude_variance_norm=min(1.0, alt_range / 5000.0),
            hover_proportion=hover_prop,
            path_linearity=linearity,
            coverage_area_norm=coverage,
            coastal_proportion=coastal,
            infrastructure_score=0.5,
        )

    def _to_list(self, fv: FlightFeatureVector) -> List[float]:
        return [
            fv.altitude_norm, fv.speed_norm, fv.duration_norm,
            fv.altitude_variance_norm, fv.hover_proportion,
            fv.path_linearity, fv.coverage_area_norm,
            fv.coastal_proportion, fv.infrastructure_score,
        ]

    def fit(self, feature_vectors: List[FlightFeatureVector], max_iterations: int = 100):
        if not feature_vectors:
            return
        self.n_clusters = min(self.n_clusters, len(feature_vectors))
        data = [self._to_list(fv) for fv in feature_vectors]
        self.centroids = self._init_centroids_pp(data)
        assignments = [0] * len(data)

        for _ in range(max_iterations):
            new_assignments = [self._nearest_centroid(x) for x in data]
            if new_assignments == assignments:
                break
            assignments = new_assignments

            new_centroids = []
            for k in range(self.n_clusters):
                pts = [data[i] for i, a in enumerate(assignments) if a == k]
                if pts:
                    new_centroids.append([sum(p[d] for p in pts) / len(pts) for d in range(len(data[0]))])
                else:
                    new_centroids.append(self.centroids[k])
            self.centroids = new_centroids

        for i, fv in enumerate(feature_vectors):
            self.cluster_labels[fv.flight_id] = assignments[i]

        self._characterize_clusters(feature_vectors, assignments)

    def _init_centroids_pp(self, data: List[List[float]]) -> List[List[float]]:
        import random
        centroids = [random.choice(data)]
        while len(centroids) < self.n_clusters:
            distances = [min(self._euclidean(x, c) ** 2 for c in centroids) for x in data]
            total = sum(distances)
            if total == 0:
                centroids.append(random.choice(data))
                continue
            probs = [d / total for d in distances]
            r = random.random()
            cumulative = 0.0
            for i, p in enumerate(probs):
                cumulative += p
                if r <= cumulative:
                    centroids.append(data[i])
                    break
        return centroids

    def _nearest_centroid(self, point: List[float]) -> int:
        distances = [self._euclidean(point, c) for c in self.centroids]
        return distances.index(min(distances))

    def _euclidean(self, a: List[float], b: List[float]) -> float:
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    def _compute_linearity(self, track_points: List[Dict]) -> float:
        if len(track_points) < 2:
            return 1.0

        def dist(p1, p2):
            from math import sqrt
            return sqrt(
                ((p2.get("latitude") or 0) - (p1.get("latitude") or 0)) ** 2 +
                ((p2.get("longitude") or 0) - (p1.get("longitude") or 0)) ** 2
            )

        total_path = sum(dist(track_points[i], track_points[i + 1]) for i in range(len(track_points) - 1))
        direct = dist(track_points[0], track_points[-1])
        if total_path == 0:
            return 1.0
        return min(1.0, direct / total_path)

    def _compute_coverage_norm(self, track_points: List[Dict]) -> float:
        if len(track_points) < 2:
            return 0.0
        lats = [(p.get("latitude") or 0) for p in track_points]
        lons = [(p.get("longitude") or 0) for p in track_points]
        area = (max(lats) - min(lats)) * (max(lons) - min(lons))
        return min(1.0, area / (0.75 * 0.65))

    def _characterize_clusters(self, feature_vectors: List[FlightFeatureVector],
                               assignments: List[int]):
        for k in range(self.n_clusters):
            members = [feature_vectors[i] for i, a in enumerate(assignments) if a == k]
            if not members:
                continue
            n = len(members)
            avg_alt = sum(m.altitude_norm for m in members) / n
            avg_hover = sum(m.hover_proportion for m in members) / n
            avg_linear = sum(m.path_linearity for m in members) / n
            avg_coastal = sum(m.coastal_proportion for m in members) / n
            avg_speed = sum(m.speed_norm for m in members) / n
            avg_duration = sum(m.duration_norm for m in members) / n
            callsigns = list(set(m.callsign for m in members))
            inferred = self._infer_cluster_mission(avg_alt, avg_hover, avg_linear, avg_coastal, avg_speed)
            self.cluster_profiles[k] = {
                "cluster_id": k, "size": n, "callsigns": callsigns,
                "avg_altitude_norm": avg_alt, "avg_hover_proportion": avg_hover,
                "avg_path_linearity": avg_linear, "avg_coastal_proportion": avg_coastal,
                "avg_speed_norm": avg_speed, "avg_duration_norm": avg_duration,
                "inferred_mission": inferred,
            }

    def _infer_cluster_mission(self, alt: float, hover: float, linear: float,
                               coastal: float, speed: float) -> str:
        if hover > 0.5 and linear < 0.4:
            return "Search / Patrol Operations"
        if hover > 0.4 and alt < 0.3:
            return "Power Line Inspection"
        if linear > 0.8 and speed > 0.6:
            return "Emergency Transit"
        if coastal > 0.7 and linear > 0.5:
            return "Maritime Patrol"
        if linear > 0.7 and hover < 0.1:
            return "Charter / Point-to-Point"
        return "General / Unknown"

    def get_cluster_report(self) -> str:
        lines = ["\n" + "═" * 60, "  BEHAVIORAL CLUSTER ANALYSIS", "═" * 60]
        for k, profile in sorted(self.cluster_profiles.items()):
            lines.append(f"\n  CLUSTER {k}: {profile['inferred_mission']}")
            lines.append(f"  ─────────────────────────────────────")
            lines.append(f"  Members:    {profile['size']} flights")
            lines.append(f"  Aircraft:   {', '.join(profile['callsigns'][:5])}")
            lines.append(f"  Avg alt:    {profile['avg_altitude_norm']*100:.0f}% of 10,000 ft")
            lines.append(f"  Hover:      {profile['avg_hover_proportion']*100:.0f}% of flight time")
            lines.append(f"  Linearity:  {profile['avg_path_linearity']*100:.0f}% (100=straight)")
            lines.append(f"  Coastal:    {profile['avg_coastal_proportion']*100:.0f}% near coast")
        lines.append("\n" + "═" * 60)
        return "\n".join(lines)


# ============================================================================
# MARKOV CHAIN PREDICTOR
# ============================================================================

@dataclass
class FlightState:
    callsign: str
    hour_of_day: int
    day_of_week: int
    last_mission: str

    def key(self) -> str:
        return f"{self.callsign}|{self.hour_of_day // 3}|{self.day_of_week}|{self.last_mission}"


class MarkovChainPredictor:
    def __init__(self, db_path: str = str(Path.home() / "flight_database.db")):
        self.db_path = db_path
        self.transition_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.transition_probs: Dict[str, Dict[str, float]] = {}

    def train(self, flights: List[Dict]):
        sorted_flights = sorted(flights, key=lambda f: (f.get("callsign", ""), f.get("takeoff_time", "")))
        prev_by_callsign: Dict[str, Dict] = {}

        for flight in sorted_flights:
            callsign = flight.get("callsign", "UNKNOWN")
            takeoff = flight.get("takeoff_time", "")
            mission = flight.get("mission_type") or MissionType.UNKNOWN.value

            try:
                dt = datetime.fromisoformat(takeoff)
                hour, dow = dt.hour, dt.weekday()
            except Exception:
                continue

            if callsign in prev_by_callsign:
                prev = prev_by_callsign[callsign]
                state = FlightState(
                    callsign=callsign,
                    hour_of_day=prev["hour"],
                    day_of_week=prev["dow"],
                    last_mission=prev["mission"],
                )
                self.transition_counts[state.key()][mission] += 1

            prev_by_callsign[callsign] = {"hour": hour, "dow": dow, "mission": mission}

        self._compute_probabilities()
        print(f"  Markov chain trained on {len(flights)} flights")
        print(f"  Unique states observed: {len(self.transition_probs)}")

    def _compute_probabilities(self):
        for state_key, transitions in self.transition_counts.items():
            total = sum(transitions.values())
            self.transition_probs[state_key] = {m: c / total for m, c in transitions.items()}

    def predict(self, callsign: str, hour: int, day_of_week: int,
                last_mission: str) -> Dict[str, float]:
        state = FlightState(callsign=callsign, hour_of_day=hour,
                            day_of_week=day_of_week, last_mission=last_mission)
        probs = self.transition_probs.get(state.key())
        if probs:
            return dict(sorted(probs.items(), key=lambda x: x[1], reverse=True))
        return self._base_rate_prediction(callsign)

    def _base_rate_prediction(self, callsign: str) -> Dict[str, float]:
        if "5854Z" in callsign:
            return {
                MissionType.POWER_INSPECTION.value: 0.70,
                MissionType.EMERGENCY_RESPONSE.value: 0.15,
                MissionType.DISASTER_RESPONSE.value: 0.10,
                MissionType.UNKNOWN.value: 0.05,
            }
        if "6062" in callsign:
            return {
                MissionType.SEARCH_AND_RESCUE.value: 0.50,
                MissionType.MARITIME_PATROL.value: 0.35,
                MissionType.EMERGENCY_RESPONSE.value: 0.10,
                MissionType.UNKNOWN.value: 0.05,
            }
        if "767PD" in callsign:
            return {
                MissionType.LAW_ENFORCEMENT.value: 0.60,
                MissionType.EMERGENCY_RESPONSE.value: 0.25,
                MissionType.ANTI_SMUGGLING.value: 0.10,
                MissionType.UNKNOWN.value: 0.05,
            }
        return {MissionType.UNKNOWN.value: 1.0}

    def get_prediction_report(self, callsign: str, hour: int,
                              day_of_week: int, last_mission: str) -> str:
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        probs = self.predict(callsign, hour, day_of_week, last_mission)
        lines = [
            f"\n  NEXT MISSION PREDICTION FOR {callsign}",
            f"  Conditions: {days[day_of_week]} at {hour:02d}:00, last mission: {last_mission}",
            f"  ─────────────────────────────────────────────",
        ]
        for mission, prob in list(probs.items())[:5]:
            bar = "█" * int(prob * 20)
            lines.append(f"  {mission:<32} {bar} {prob*100:.1f}%")
        return "\n".join(lines)


# ============================================================================
# PHASE 3 PIPELINE
# ============================================================================

class Phase3Pipeline:
    def __init__(self, db_path: str = str(Path.home() / "flight_database.db")):
        self.db_path = db_path
        self.scorer = MultiFactorMissionScorer(db_path)
        self.clusterer = BehavioralClusterer(n_clusters=6)
        self.predictor = MarkovChainPredictor(db_path)
        self._init_phase3_tables()

    def _init_phase3_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mission_scores (
                flight_id TEXT,
                mission_type TEXT,
                total_score REAL,
                confidence_level TEXT,
                signal_scores TEXT,
                explanation TEXT,
                scored_at TEXT,
                PRIMARY KEY (flight_id, mission_type)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cluster_assignments (
                flight_id TEXT PRIMARY KEY,
                cluster_id INTEGER,
                cluster_label TEXT,
                assigned_at TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS markov_transitions (
                state_key TEXT,
                next_mission TEXT,
                probability REAL,
                observation_count INTEGER,
                PRIMARY KEY (state_key, next_mission)
            )
        ''')
        conn.commit()
        conn.close()

    def run(self):
        print("\n" + "═" * 60)
        print("  PHASE 3: MISSION INFERENCE ENGINE")
        print("═" * 60)

        flights = self._load_flights()
        print(f"\n  Loaded {len(flights)} flights from database")

        if not flights:
            print("  No flights found. Run Phase 0/1 first.")
            return

        print("\n  Step 1: Multi-factor mission scoring...")
        feature_vectors = []
        for flight in flights:
            track = self._load_track(flight["flight_id"])
            scores = self.scorer.score_flight(flight, track, [], [])
            if scores:
                self._save_mission_score(flight["flight_id"], scores[0])
                self._update_flight_mission(flight["flight_id"], scores[0].mission_type.value)
            fv = self.clusterer.extract_feature_vector(flight, track)
            feature_vectors.append(fv)
        print(f"  ✓ Scored {len(flights)} flights")

        print("\n  Step 2: Behavioral clustering...")
        if len(feature_vectors) >= 2:
            self.clusterer.fit(feature_vectors)
            self._save_cluster_assignments(feature_vectors)
            print(self.clusterer.get_cluster_report())
        else:
            print("  Not enough flights for clustering (need ≥ 2)")

        print("\n  Step 3: Training Markov chain predictor...")
        self.predictor.train(self._load_flights())
        self._save_markov_transitions()
        print("  ✓ Predictor trained")

        print("\n  Step 4: Sample predictions")
        for callsign, hour, dow, last in [
            ("N5854Z", 8, 0, MissionType.POWER_INSPECTION.value),
            ("C6062", 14, 2, MissionType.MARITIME_PATROL.value),
            ("N767PD", 22, 4, MissionType.LAW_ENFORCEMENT.value),
        ]:
            print(self.predictor.get_prediction_report(callsign, hour, dow, last))

        print("\n  ✓ Phase 3 complete")

    def _load_flights(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM flights ORDER BY takeoff_time")
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    def _load_track(self, flight_id: str) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM track_points WHERE flight_id = ? ORDER BY timestamp",
            (flight_id,)
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    def _save_mission_score(self, flight_id: str, score: MissionScore):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO mission_scores
            (flight_id, mission_type, total_score, confidence_level,
             signal_scores, explanation, scored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            flight_id, score.mission_type.value, score.total_score,
            score.confidence_level, json.dumps(score.signal_scores),
            json.dumps(score.explanation), datetime.utcnow().isoformat(),
        ))
        conn.commit()
        conn.close()

    def _update_flight_mission(self, flight_id: str, mission_type: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE flights SET mission_type = ? WHERE flight_id = ?",
            (mission_type, flight_id)
        )
        conn.commit()
        conn.close()

    def _save_cluster_assignments(self, feature_vectors: List[FlightFeatureVector]):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        for fv in feature_vectors:
            cluster_id = self.clusterer.cluster_labels.get(fv.flight_id, -1)
            label = self.clusterer.cluster_profiles.get(cluster_id, {}).get("inferred_mission", "Unknown")
            cursor.execute('''
                INSERT OR REPLACE INTO cluster_assignments
                (flight_id, cluster_id, cluster_label, assigned_at)
                VALUES (?, ?, ?, ?)
            ''', (fv.flight_id, cluster_id, label, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

    def _save_markov_transitions(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        for state_key, transitions in self.predictor.transition_probs.items():
            for mission, prob in transitions.items():
                count = self.predictor.transition_counts[state_key].get(mission, 0)
                cursor.execute('''
                    INSERT OR REPLACE INTO markov_transitions
                    (state_key, next_mission, probability, observation_count)
                    VALUES (?, ?, ?, ?)
                ''', (state_key, mission, prob, count))
        conn.commit()
        conn.close()


if __name__ == "__main__":
    pipeline = Phase3Pipeline()
    pipeline.run()
