"""Aircraft identity resolution without mission or operational-purpose inference."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from skywatcher.core.known_operators import IDENTIFIER_ALIASES, KNOWN_OPERATORS

CALLSIGN_PREFIXES = {
    "N": {"country": "United States", "registry": "FAA"},
    "YN": {"country": "Nicaragua", "registry": "Civil aviation"},
}
AIRCRAFT_TYPE_MISSIONS: dict[str, str] = {}


def normalize_identifier(value: str) -> str:
    return "".join(ch for ch in value.upper().strip() if ch.isalnum())


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
    data_source: str = "unknown"
    provenance: Dict = field(default_factory=dict)

    def is_stale(self, threshold_days: int = 30) -> bool:
        if not self.last_seen:
            return True
        try:
            last = datetime.fromisoformat(self.last_seen)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - last).days > threshold_days
        except (ValueError, TypeError):
            return True


class AircraftIntelligence:
    """Resolve exact source-declared identity fields and observed history only."""

    def __init__(self, db_path: str = str(Path.home() / "flight_database.db")):
        self.db_path = db_path

    def lookup_aircraft(self, callsign: str) -> AircraftProfile:
        normalized = normalize_identifier(callsign)
        canonical = IDENTIFIER_ALIASES.get(normalized, normalized)
        entry = KNOWN_OPERATORS.get(canonical)
        profile = AircraftProfile(callsign=callsign)

        if entry:
            verified = entry.get("verified_fields", {})
            profile.aircraft_type = verified.get("aircraft_type", "")
            profile.owner = verified.get("owner", "Unknown")
            profile.operator = verified.get("operator", "Unknown")
            profile.country = verified.get("country", "Unknown")
            profile.confidence_level = float(verified.get("confidence_level", 0.0))
            profile.provenance = dict(entry.get("provenance", {}))
            profile.data_source = "verified_registry" if verified else "unverified_registry"
        else:
            profile.data_source = "observed_history"
            for prefix, info in sorted(CALLSIGN_PREFIXES.items(), key=lambda item: -len(item[0])):
                if normalized.startswith(prefix):
                    profile.country = info["country"]
                    break

        self._enrich_from_db(profile)
        profile.primary_mission = "Unknown"
        profile.secondary_missions = []
        profile.operational_patterns = {}
        return profile

    def _deduce_profile(self, callsign: str) -> AircraftProfile:
        """Compatibility helper; active deduction is identity/history-only."""
        return self.lookup_aircraft(callsign)

    def _enrich_from_db(self, profile: AircraftProfile) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT aircraft_type, operator, COUNT(*), MIN(takeoff_time), MAX(takeoff_time) "
                    "FROM flights WHERE callsign = ?",
                    (profile.callsign,),
                ).fetchone()
            if row:
                aircraft_type, operator, count, first_seen, last_seen = row
                if not profile.aircraft_type:
                    profile.aircraft_type = aircraft_type or ""
                if profile.operator == "Unknown":
                    profile.operator = operator or "Unknown"
                profile.total_flights = count or 0
                profile.first_seen = first_seen or ""
                profile.last_seen = last_seen or ""
        except (sqlite3.Error, OSError):
            return

    def compile_intelligence_report(self, callsign: str) -> str:
        profile = self.lookup_aircraft(callsign)
        return "\n".join(
            [
                f"AIRCRAFT PROFILE: {profile.callsign}",
                f"Aircraft Type: {profile.aircraft_type or 'Unknown'}",
                f"Owner: {profile.owner}",
                f"Operator: {profile.operator}",
                f"Country: {profile.country}",
                "Role: Unknown (not inferred)",
                f"Total observed flights: {profile.total_flights}",
                f"First seen: {profile.first_seen or 'N/A'}",
                f"Last seen: {profile.last_seen or 'N/A'}",
                f"Data source: {profile.data_source}",
            ]
        )

    def update_aircraft_profiles_table(self) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                callsigns = [row[0] for row in conn.execute("SELECT DISTINCT callsign FROM flights WHERE callsign != ''")]
        except (sqlite3.Error, OSError):
            return

        for callsign in callsigns:
            profile = self.lookup_aircraft(callsign)
            try:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO aircraft_profiles
                        (callsign, aircraft_type, owner, operator, primary_mission,
                         confidence_level, total_flights, first_seen, last_seen,
                         operational_patterns)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            profile.callsign,
                            profile.aircraft_type,
                            profile.owner,
                            profile.operator,
                            "Unknown",
                            profile.confidence_level,
                            profile.total_flights,
                            profile.first_seen,
                            profile.last_seen,
                            json.dumps({}),
                        ),
                    )
                    conn.commit()
            except (sqlite3.Error, OSError):
                continue

    def find_unknown(self, callsigns: List[str]) -> List[str]:
        unknown: List[str] = []
        for callsign in callsigns:
            normalized = normalize_identifier(callsign)
            canonical = IDENTIFIER_ALIASES.get(normalized, normalized)
            if canonical not in KNOWN_OPERATORS:
                unknown.append(callsign)
        return unknown

    @property
    def profile_completeness(self) -> float:
        """Fraction of registry entries with verified identity fields and provenance."""
        if not KNOWN_OPERATORS:
            return 0.0
        complete = 0
        for entry in KNOWN_OPERATORS.values():
            fields = entry.get("verified_fields", {})
            provenance = entry.get("provenance", {})
            if fields and all(
                provenance.get(key)
                for key in ("source_uri", "source_record_id", "captured_at", "sha256")
            ):
                complete += 1
        return complete / len(KNOWN_OPERATORS)
