"""QUARANTINED — DO NOT USE IN NEW CODE.

This module performs heuristic "why is this flying" mission inference
(callsign/duration/altitude/speed scoring against named mission categories).
It contradicts the repository's evidence-preservation posture
(pipeline/rlsm_ontology_gate.py's do_not_assume_intentional,
skywatcher.fusion's operational_cueing=False) and the explicit requirement
that no module in this pipeline infer intent or operational purpose.

It is kept ONLY for backward compatibility with the pre-existing
aircraft_intelligence.FlightMissionAnalyzer import path. It is EXCLUDED from
skywatcher.fpim's active API, is not imported by any core/satim/fpim/corrim
module, and MUST NOT be reintroduced into FPIM. See
docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md.

MissionAnalysis      — Result of a heuristic mission deduction
FlightMissionAnalyzer — Pattern-based mission deduction from flight records
analyze_all_aircraft  — Convenience CLI-style entry point
"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from skywatcher.core.known_operators import KNOWN_OPERATORS
from skywatcher.fpim.aircraft_profile import AircraftIntelligence


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
