"""
AIRCRAFT INTELLIGENCE LAYER

AircraftProfile      — Structured profile for a known or deduced aircraft
AircraftIntelligence — N-number → owner/operator/mission lookup
FlightMissionAnalyzer — Pattern-based mission deduction from flight records
"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime


# ============================================================================
# KNOWN OPERATORS DATABASE
# ============================================================================

# Maps callsign substrings → operator metadata
KNOWN_OPERATORS = {
    "N5854Z": {
        "owner": "Puerto Rico Electric Power Authority",
        "operator": "PREPA",
        "aircraft_type": "Airbus H125",
        "primary_mission": "Power Line Inspection",
        "secondary_missions": ["Emergency Response", "Disaster Response / Damage Assessment"],
        "confidence_level": 0.98,
        "operational_patterns": {
            "typical_altitude": "500-3000 ft AGL",
            "typical_airspeed": "40-120 mph",
            "operating_hours": "Daytime (07:00-18:00 local)",
            "high_activity_regions": ["South Coast Corridor", "Central Interior Grid"],
            "typical_duration_hours": "2-8",
        },
    },
    "C6062": {
        "owner": "United States Coast Guard",
        "operator": "USCG Air Station Borinquen",
        "aircraft_type": "Sikorsky MH-60T Jayhawk",
        "primary_mission": "Search & Rescue",
        "secondary_missions": ["Maritime Patrol", "Anti-Smuggling / Interdiction", "Emergency Response"],
        "confidence_level": 0.97,
        "operational_patterns": {
            "typical_altitude": "200-8000 ft AGL",
            "typical_airspeed": "100-160 mph",
            "operating_hours": "24/7",
            "high_activity_regions": ["Mona Passage", "Caribbean Sea", "Puerto Rico coastline"],
            "typical_duration_hours": "2-6",
        },
    },
    "N767PD": {
        "owner": "Puerto Rico Police Department",
        "operator": "FURA (Fuerzas Unidas de Rápida Acción)",
        "aircraft_type": "Bell 429 GlobalRanger",
        "primary_mission": "Law Enforcement",
        "secondary_missions": ["Emergency Response", "Anti-Smuggling / Interdiction"],
        "confidence_level": 0.96,
        "operational_patterns": {
            "typical_altitude": "300-4000 ft AGL",
            "typical_airspeed": "30-140 mph",
            "operating_hours": "24/7",
            "high_activity_regions": ["San Juan Metro", "Bayamon", "Carolina"],
            "typical_duration_hours": "1-4",
        },
    },
    "N684JB": {
        "owner": "Private owner",
        "operator": "Private/Charter",
        "aircraft_type": "Airbus H130",
        "primary_mission": "Private Charter",
        "secondary_missions": ["Training Flight"],
        "confidence_level": 0.88,
        "operational_patterns": {
            "typical_altitude": "2000-8000 ft AGL",
            "typical_airspeed": "90-160 mph",
            "operating_hours": "Daytime",
            "high_activity_regions": ["San Juan", "Ponce", "Aguadilla"],
            "typical_duration_hours": "0.5-2",
        },
    },
    # --- Additional known profiles ---
    "N911PR": {
        "owner": "Puerto Rico Department of Health",
        "operator": "Puerto Rico Emergency Medical Services",
        "aircraft_type": "Airbus H145",
        "primary_mission": "Medical/Emergency Transport",
        "secondary_missions": ["Emergency Response", "Disaster Response / Damage Assessment"],
        "confidence_level": 0.95,
        "operational_patterns": {
            "typical_altitude": "500-6000 ft AGL",
            "typical_airspeed": "80-170 mph",
            "operating_hours": "24/7",
            "high_activity_regions": ["San Juan", "Ponce", "Mayaguez", "Arecibo"],
            "typical_duration_hours": "0.5-3",
        },
    },
    "N304NG": {
        "owner": "National Guard Bureau",
        "operator": "Puerto Rico Army National Guard",
        "aircraft_type": "Sikorsky UH-60 Black Hawk",
        "primary_mission": "Military / National Guard Operations",
        "secondary_missions": ["Disaster Response / Damage Assessment", "Search & Rescue", "Emergency Response"],
        "confidence_level": 0.93,
        "operational_patterns": {
            "typical_altitude": "500-10000 ft AGL",
            "typical_airspeed": "100-180 mph",
            "operating_hours": "Daytime (06:00-22:00 local)",
            "high_activity_regions": ["Salinas Army Base", "Muñiz Air Base", "Aguadilla"],
            "typical_duration_hours": "1-5",
        },
    },
    "N448CB": {
        "owner": "U.S. Customs and Border Protection",
        "operator": "CBP Air and Marine Operations",
        "aircraft_type": "Sikorsky UH-60 Black Hawk",
        "primary_mission": "Anti-Smuggling / Interdiction",
        "secondary_missions": ["Maritime Patrol", "Law Enforcement"],
        "confidence_level": 0.94,
        "operational_patterns": {
            "typical_altitude": "200-8000 ft AGL",
            "typical_airspeed": "100-180 mph",
            "operating_hours": "24/7",
            "high_activity_regions": ["Mona Passage", "Vieques", "Culebra", "North Coast"],
            "typical_duration_hours": "2-6",
        },
    },
    "N229AE": {
        "owner": "AeroMed Puerto Rico LLC",
        "operator": "AeroMed",
        "aircraft_type": "Bell 429 GlobalRanger",
        "primary_mission": "Medical/Emergency Transport",
        "secondary_missions": ["Emergency Response"],
        "confidence_level": 0.91,
        "operational_patterns": {
            "typical_altitude": "1000-7000 ft AGL",
            "typical_airspeed": "100-160 mph",
            "operating_hours": "24/7",
            "high_activity_regions": ["San Juan Metro", "Ponce", "Arecibo", "Mayaguez"],
            "typical_duration_hours": "0.3-2",
        },
    },
    "N87TV": {
        "owner": "Telemundo Puerto Rico",
        "operator": "Telemundo / WKAQ-TV",
        "aircraft_type": "Robinson R44",
        "primary_mission": "News / Media Aerial Coverage",
        "secondary_missions": ["Traffic Monitoring"],
        "confidence_level": 0.89,
        "operational_patterns": {
            "typical_altitude": "1000-4000 ft AGL",
            "typical_airspeed": "80-130 mph",
            "operating_hours": "Daytime (06:00-21:00 local)",
            "high_activity_regions": ["San Juan Metro", "Bayamon", "Carolina", "Guaynabo"],
            "typical_duration_hours": "0.5-3",
        },
    },
    "N521PR": {
        "owner": "Puerto Rico Port Authority",
        "operator": "PRPA / Port Security",
        "aircraft_type": "Airbus H125",
        "primary_mission": "Port and Maritime Surveillance",
        "secondary_missions": ["Anti-Smuggling / Interdiction", "Emergency Response"],
        "confidence_level": 0.87,
        "operational_patterns": {
            "typical_altitude": "200-3000 ft AGL",
            "typical_airspeed": "40-120 mph",
            "operating_hours": "Daytime (06:00-20:00 local)",
            "high_activity_regions": ["San Juan Bay", "Ponce Harbor", "Mayaguez Port"],
            "typical_duration_hours": "1-4",
        },
    },
    "N172FA": {
        "owner": "Federal Aviation Administration",
        "operator": "FAA Flight Standards District Office",
        "aircraft_type": "Cessna 172",
        "primary_mission": "Aviation Regulatory / Inspection",
        "secondary_missions": ["Training Flight"],
        "confidence_level": 0.85,
        "operational_patterns": {
            "typical_altitude": "2000-9000 ft AGL",
            "typical_airspeed": "100-140 mph",
            "operating_hours": "Daytime (08:00-17:00 local)",
            "high_activity_regions": ["Luis Munoz Marin Intl", "Rafael Hernandez Airport", "Mercedita Airport"],
            "typical_duration_hours": "1-4",
        },
    },
    "N388DR": {
        "owner": "DroneUp LLC",
        "operator": "DroneUp / Commercial UAS Operations",
        "aircraft_type": "DJI Matrice 300 RTK",
        "primary_mission": "Commercial UAS / Survey",
        "secondary_missions": ["Disaster Response / Damage Assessment", "Power Line Inspection"],
        "confidence_level": 0.82,
        "operational_patterns": {
            "typical_altitude": "100-400 ft AGL",
            "typical_airspeed": "10-50 mph",
            "operating_hours": "Daytime (07:00-19:00 local)",
            "high_activity_regions": ["Humacao", "Caguas", "San Juan Industrial Zones"],
            "typical_duration_hours": "0.5-2",
        },
    },
    "N960PR": {
        "owner": "Puerto Rico Forestry Service",
        "operator": "DRNA Recursos Naturales",
        "aircraft_type": "Airbus AS350 B3",
        "primary_mission": "Environmental / Forestry Patrol",
        "secondary_missions": ["Disaster Response / Damage Assessment", "Search & Rescue"],
        "confidence_level": 0.86,
        "operational_patterns": {
            "typical_altitude": "300-5000 ft AGL",
            "typical_airspeed": "60-140 mph",
            "operating_hours": "Daytime (07:00-17:00 local)",
            "high_activity_regions": ["El Yunque", "Toro Negro Forest", "Maricao"],
            "typical_duration_hours": "1-5",
        },
    },
    "N741LE": {
        "owner": "Puerto Rico Department of Justice",
        "operator": "PR DOJ / Criminal Investigations Bureau",
        "aircraft_type": "Bell 407",
        "primary_mission": "Law Enforcement",
        "secondary_missions": ["Anti-Smuggling / Interdiction", "Emergency Response"],
        "confidence_level": 0.90,
        "operational_patterns": {
            "typical_altitude": "500-5000 ft AGL",
            "typical_airspeed": "80-160 mph",
            "operating_hours": "24/7",
            "high_activity_regions": ["San Juan", "Bayamon", "Ponce", "Caguas"],
            "typical_duration_hours": "1-4",
        },
    },
}

# Prefix-based operator inference when exact match is not found
CALLSIGN_PREFIXES = {
    "N": {"country": "United States", "registry": "FAA"},
    "C": {"country": "United States (USCG/military)", "registry": "FAA/DoD"},
    "YN": {"country": "Nicaragua", "registry": "Civil aviation"},
}

# Aircraft type to mission profile mapping
AIRCRAFT_TYPE_MISSIONS = {
    "H125": "Power Line Inspection",
    "AS50": "Power Line Inspection",
    "MH60": "Search & Rescue",
    "MH-60": "Search & Rescue",
    "B429": "Law Enforcement",
    "H130": "Private Charter",
    "EC35": "Emergency Response",
    "AW139": "Emergency Response",
    "S76": "Medical/Emergency Transport",
    "R44": "Training Flight",
    "R66": "Training Flight",
}


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class AircraftProfile:
    callsign: str
    aircraft_type: str = ""
    owner: str = "Unknown"
    operator: str = "Unknown"
    country: str = "Unknown"
    primary_mission: str = "Unknown"
    secondary_missions: List[str] = field(default_factory=list)
    confidence_level: float = 0.0
    operational_patterns: Dict = field(default_factory=dict)
    total_flights: int = 0
    first_seen: str = ""
    last_seen: str = ""
    data_source: str = "deduced"  # "known_db", "deduced", "unknown"

    def is_stale(self, threshold_days: int = 30) -> bool:
        """Return True if last_seen is older than threshold_days (default 30)."""
        if not self.last_seen:
            return True
        try:
            last = datetime.fromisoformat(self.last_seen)
            delta = datetime.utcnow() - last
            return delta.days > threshold_days
        except (ValueError, TypeError):
            return True


@dataclass
class MissionAnalysis:
    flight_id: str
    callsign: str
    route: str
    duration_minutes: int
    max_altitude_ft: int
    avg_speed_mph: float
    likely_mission: str
    mission_confidence: float
    evidence: List[str] = field(default_factory=list)


# ============================================================================
# AIRCRAFT INTELLIGENCE
# ============================================================================

class AircraftIntelligence:
    """
    Looks up aircraft ownership and mission from known database,
    then deduces from available signals if not found.
    """

    def __init__(self, db_path: str = str(Path.home() / "flight_database.db")):
        self.db_path = db_path

    def lookup_aircraft(self, callsign: str) -> AircraftProfile:
        """Return AircraftProfile for callsign. Tries DB first, then deduction."""
        # 1. Exact match in known operators
        for key, data in KNOWN_OPERATORS.items():
            if key in callsign or callsign in key:
                profile = AircraftProfile(
                    callsign=callsign,
                    aircraft_type=data["aircraft_type"],
                    owner=data["owner"],
                    operator=data["operator"],
                    primary_mission=data["primary_mission"],
                    secondary_missions=data["secondary_missions"],
                    confidence_level=data["confidence_level"],
                    operational_patterns=data["operational_patterns"],
                    data_source="known_db",
                )
                self._enrich_from_db(profile)
                return profile

        # 2. Deduced from callsign prefix and DB history
        profile = self._deduce_profile(callsign)
        self._enrich_from_db(profile)
        return profile

    def _deduce_profile(self, callsign: str) -> AircraftProfile:
        """Infer profile from N-number structure and flight history."""
        profile = AircraftProfile(
            callsign=callsign,
            data_source="deduced",
        )

        # Country from prefix
        for prefix, info in CALLSIGN_PREFIXES.items():
            if callsign.startswith(prefix):
                profile.country = info["country"]
                break

        # Try to find aircraft type from flight history and map to mission
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT aircraft_type, operator FROM flights WHERE callsign = ? LIMIT 1",
                (callsign,)
            )
            row = cursor.fetchone()
            conn.close()

            if row:
                a_type, operator = row
                profile.aircraft_type = a_type or ""
                profile.operator = operator or "Unknown"
                for type_key, mission in AIRCRAFT_TYPE_MISSIONS.items():
                    if type_key in (a_type or "").upper():
                        profile.primary_mission = mission
                        profile.confidence_level = 0.60
                        break
        except Exception:
            pass

        if not profile.primary_mission:
            profile.primary_mission = "Unknown"
            profile.confidence_level = 0.20

        return profile

    def _enrich_from_db(self, profile: AircraftProfile):
        """Add flight statistics from database."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*), MIN(takeoff_time), MAX(takeoff_time)
                FROM flights WHERE callsign = ?
            ''', (profile.callsign,))
            row = cursor.fetchone()
            conn.close()

            if row and row[0]:
                profile.total_flights = row[0]
                profile.first_seen = row[1] or ""
                profile.last_seen = row[2] or ""
        except Exception:
            pass

    def compile_intelligence_report(self, callsign: str) -> str:
        """Human-readable intelligence report for a callsign."""
        profile = self.lookup_aircraft(callsign)

        lines = [
            "╔" + "═" * 68 + "╗",
            "║" + f"  AIRCRAFT INTELLIGENCE: {callsign}".center(68) + "║",
            "╚" + "═" * 68 + "╝",
            "",
            f"  Callsign:          {profile.callsign}",
            f"  Aircraft Type:     {profile.aircraft_type or 'Unknown'}",
            f"  Owner:             {profile.owner}",
            f"  Operator:          {profile.operator}",
            f"  Country:           {profile.country}",
            "",
            f"  Primary Mission:   {profile.primary_mission}",
        ]

        if profile.secondary_missions:
            lines.append(f"  Secondary Missions: {', '.join(profile.secondary_missions)}")

        lines += [
            f"  Confidence:        {profile.confidence_level * 100:.0f}%",
            f"  Data Source:       {profile.data_source}",
            "",
        ]

        if profile.total_flights:
            lines += [
                "  ACTIVITY",
                "  ─────────────────────────────────────────────",
                f"  Total flights:   {profile.total_flights}",
                f"  First seen:      {profile.first_seen or 'N/A'}",
                f"  Last seen:       {profile.last_seen or 'N/A'}",
                "",
            ]

        if profile.operational_patterns:
            lines += ["  OPERATIONAL PATTERNS", "  ─────────────────────────────────────────────"]
            for key, value in profile.operational_patterns.items():
                label = key.replace("_", " ").title()
                if isinstance(value, list):
                    value = ", ".join(value)
                lines.append(f"  {label:<25} {value}")
            lines.append("")

        lines.append("═" * 70)
        return "\n".join(lines)

    def update_aircraft_profiles_table(self):
        """Refresh the aircraft_profiles table in the database."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT callsign FROM flights WHERE callsign != ''")
            callsigns = [r[0] for r in cursor.fetchall()]
            conn.close()
        except Exception:
            return

        for callsign in callsigns:
            profile = self.lookup_aircraft(callsign)
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                import json
                cursor.execute('''
                    INSERT OR REPLACE INTO aircraft_profiles
                    (callsign, aircraft_type, owner, operator, primary_mission,
                     confidence_level, total_flights, first_seen, last_seen,
                     operational_patterns)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    profile.callsign, profile.aircraft_type, profile.owner,
                    profile.operator, profile.primary_mission,
                    profile.confidence_level, profile.total_flights,
                    profile.first_seen, profile.last_seen,
                    json.dumps(profile.operational_patterns),
                ))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def find_unknown(self, callsigns: List[str]) -> List[str]:
        """Return the subset of callsigns that have no profile match in KNOWN_OPERATORS.

        A callsign is considered 'unknown' when neither a substring match nor a
        prefix match resolves it to a known entry — i.e. it would fall through to
        the 'deduced' path with data_source == 'deduced'.
        """
        unknown: List[str] = []
        for cs in callsigns:
            matched = False
            for key in KNOWN_OPERATORS:
                if key in cs or cs in key:
                    matched = True
                    break
            if not matched:
                unknown.append(cs)
        return unknown

    @property
    def profile_completeness(self) -> float:
        """Fraction of known profiles that have all core fields filled (0.0–1.0).

        Core fields checked: aircraft_type, owner, operator, primary_mission,
        confidence_level > 0, and at least one operational_patterns entry.
        """
        if not KNOWN_OPERATORS:
            return 0.0

        complete_count = 0
        for data in KNOWN_OPERATORS.values():
            if (
                data.get("aircraft_type", "").strip()
                and data.get("owner", "").strip()
                and data.get("operator", "").strip()
                and data.get("primary_mission", "").strip()
                and data.get("confidence_level", 0.0) > 0.0
                and data.get("operational_patterns")
            ):
                complete_count += 1
        return complete_count / len(KNOWN_OPERATORS)


# ============================================================================
# FLIGHT MISSION ANALYZER
# ============================================================================

class FlightMissionAnalyzer:
    """
    Deduces mission type from flight record characteristics.
    Used when no direct operator match is available.
    """

    def __init__(self, db_path: str = str(Path.home() / "flight_database.db")):
        self.db_path = db_path

    def analyze_flight_pattern(self, flight_id: str) -> MissionAnalysis:
        """Load a flight from DB and deduce its mission."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM flights WHERE flight_id = ?", (flight_id,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return MissionAnalysis(
                    flight_id=flight_id, callsign="", route="", duration_minutes=0,
                    max_altitude_ft=0, avg_speed_mph=0.0, likely_mission="Unknown",
                    mission_confidence=0.0,
                )
            flight = dict(row)

            cursor.execute(
                "SELECT altitude_ft FROM track_points WHERE flight_id = ?", (flight_id,)
            )
            altitudes = [r[0] for r in cursor.fetchall() if r[0]]
            conn.close()
        except Exception:
            return MissionAnalysis(
                flight_id=flight_id, callsign="", route="", duration_minutes=0,
                max_altitude_ft=0, avg_speed_mph=0.0, likely_mission="Unknown",
                mission_confidence=0.0,
            )

        callsign = flight.get("callsign", "")
        origin = flight.get("origin_airport") or "?"
        dest = flight.get("destination_airport") or "?"
        duration = flight.get("flight_duration_minutes") or 0
        max_alt = flight.get("max_altitude_ft") or 0
        avg_spd = float(flight.get("avg_speed_mph") or 0)

        mission, confidence, evidence = self._deduce_mission(
            callsign, duration, max_alt, avg_spd, altitudes
        )

        return MissionAnalysis(
            flight_id=flight_id,
            callsign=callsign,
            route=f"{origin} → {dest}",
            duration_minutes=duration,
            max_altitude_ft=max_alt,
            avg_speed_mph=avg_spd,
            likely_mission=mission,
            mission_confidence=confidence,
            evidence=evidence,
        )

    def _deduce_mission(self, callsign: str, duration_min: int,
                        max_alt_ft: int, avg_spd_mph: float,
                        altitudes: List[int]) -> tuple:
        evidence = []
        scores: Dict[str, float] = {}

        alt_variance = (max(altitudes) - min(altitudes)) if len(altitudes) > 1 else 0

        # Power inspection heuristics
        pi_score = 0.0
        if "5854Z" in callsign or "PREPA" in callsign:
            pi_score += 0.5
            evidence.append("Known PREPA operator")
        if 90 <= duration_min <= 480:
            pi_score += 0.2
        if 500 <= max_alt_ft <= 3000:
            pi_score += 0.15
        if alt_variance > 500:
            pi_score += 0.15
            evidence.append("Altitude variation consistent with terrain-following inspection")
        scores["Power Line Inspection"] = pi_score

        # SAR heuristics
        sar_score = 0.0
        if "6062" in callsign or "USCG" in callsign:
            sar_score += 0.5
            evidence.append("Known USCG operator")
        if 60 <= duration_min <= 360:
            sar_score += 0.2
        if alt_variance > 1000:
            sar_score += 0.15
            evidence.append("High altitude variance — consistent with search pattern")
        if avg_spd_mph < 80:
            sar_score += 0.15
        scores["Search & Rescue"] = sar_score

        # Law enforcement heuristics
        le_score = 0.0
        if "767PD" in callsign or "FURA" in callsign:
            le_score += 0.5
            evidence.append("Known FURA operator")
        if 30 <= duration_min <= 240:
            le_score += 0.2
        if max_alt_ft < 3000:
            le_score += 0.2
        scores["Law Enforcement"] = le_score

        # Emergency response heuristics
        er_score = 0.0
        if duration_min < 60 and avg_spd_mph > 100:
            er_score += 0.4
            evidence.append("Short high-speed flight consistent with emergency response")
        scores["Emergency Response"] = er_score

        # Maritime patrol
        mp_score = 0.0
        if "6062" in callsign and duration_min > 120:
            mp_score += 0.4
            evidence.append("USCG long-duration flight consistent with maritime patrol")
        scores["Maritime Patrol"] = mp_score

        # Charter
        ch_score = 0.0
        if "684JB" in callsign:
            ch_score += 0.5
            evidence.append("Known charter operator")
        if max_alt_ft > 3000 and avg_spd_mph > 90:
            ch_score += 0.3
        scores["Private Charter"] = ch_score

        best_mission = max(scores, key=scores.get)
        best_score = scores[best_mission]

        if best_score < 0.3:
            return "Unknown", 0.2, ["Insufficient signals for mission deduction"]

        return best_mission, min(1.0, best_score), evidence


# ============================================================================
# CONVENIENCE FUNCTION
# ============================================================================

def analyze_all_aircraft(db_path: str = str(Path.home() / "flight_database.db")):
    """Print intelligence reports for all known callsigns in database."""
    intel = AircraftIntelligence(db_path)
    intel.update_aircraft_profiles_table()

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT callsign FROM flights WHERE callsign != '' ORDER BY callsign")
        callsigns = [r[0] for r in cursor.fetchall()]
        conn.close()
    except Exception:
        callsigns = list(KNOWN_OPERATORS.keys())

    for callsign in callsigns:
        print(intel.compile_intelligence_report(callsign))


if __name__ == "__main__":
    print("Aircraft Intelligence Layer\n")
    intel = AircraftIntelligence()
    for callsign in ["N5854Z", "C6062", "N767PD", "N684JB"]:
        print(intel.compile_intelligence_report(callsign))
