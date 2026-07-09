"""
AIRCRAFT PROFILE — FPIM aircraft-identity resolution.

AircraftProfile      — Structured profile for a known or deduced aircraft
AircraftIntelligence — N-number → owner/operator/mission lookup
"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from skywatcher.core.known_operators import KNOWN_OPERATORS

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
        """Infer profile from N-number structure and flight history.

        Note: the aircraft-type -> mission fallback below (AIRCRAFT_TYPE_MISSIONS)
        is a secondary, lower-confidence mission guess distinct from the
        operator-provided KNOWN_OPERATORS ground truth above. It is preserved
        here unchanged for backward compatibility (requirement to not alter
        existing behavior); see docs/MODULE_SPEC_FPIM.md's technical-debt note
        for why it isn't quarantined alongside FlightMissionAnalyzer.
        """
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
