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
IDENTITY_FIELDS = (
    "aircraft_type",
    "owner",
    "operator",
    "country",
    "confidence_level",
)
PROVENANCE_KEYS = ("source_uri", "source_record_id", "captured_at", "sha256")


def normalize_identifier(value: str) -> str:
    return "".join(ch for ch in value.upper().strip() if ch.isalnum())


def _complete_provenance(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return all(value.get(key) for key in PROVENANCE_KEYS)


def _verified_identity_fields(entry: dict) -> tuple[dict, dict[str, dict]]:
    """Return only identity fields whose own provenance record is complete.

    ``field_provenance`` is the preferred representation. A complete shared
    ``provenance`` record remains supported when every declared field came from
    the same captured source record.
    """
    declared = entry.get("verified_fields", {})
    if not isinstance(declared, dict):
        return {}, {}
    field_provenance = entry.get("field_provenance", {})
    if not isinstance(field_provenance, dict):
        field_provenance = {}
    shared_provenance = entry.get("provenance", {})

    active: dict = {}
    active_provenance: dict[str, dict] = {}
    for field_name in IDENTITY_FIELDS:
        value = declared.get(field_name)
        if value in (None, "", [], {}):
            continue
        provenance = field_provenance.get(field_name, shared_provenance)
        if not _complete_provenance(provenance):
            continue
        active[field_name] = value
        active_provenance[field_name] = dict(provenance)
    return active, active_provenance


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
            verified, field_provenance = _verified_identity_fields(entry)
            profile.aircraft_type = str(verified.get("aircraft_type", ""))
            profile.owner = str(verified.get("owner", "Unknown"))
            profile.operator = str(verified.get("operator", "Unknown"))
            profile.country = str(verified.get("country", "Unknown"))
            profile.confidence_level = float(verified.get("confidence_level", 0.0))
            profile.provenance = {"fields": field_provenance} if field_provenance else dict(
                entry.get("provenance", {})
            )
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
        """Attach observed counts and timestamps without promoting identity fields."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT COUNT(*), MIN(takeoff_time), MAX(takeoff_time) "
                    "FROM flights WHERE callsign = ?",
                    (profile.callsign,),
                ).fetchone()
            if row:
                count, first_seen, last_seen = row
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
                callsigns = [
                    row[0]
                    for row in conn.execute(
                        "SELECT DISTINCT callsign FROM flights WHERE callsign != ''"
                    )
                ]
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
        """Fraction of registry entries whose declared identity fields are provenance-complete."""
        if not KNOWN_OPERATORS:
            return 0.0
        complete = 0
        for entry in KNOWN_OPERATORS.values():
            declared = {
                key: value
                for key, value in entry.get("verified_fields", {}).items()
                if key in IDENTITY_FIELDS and value not in (None, "", [], {})
            }
            active, _ = _verified_identity_fields(entry)
            if declared and set(active) == set(declared):
                complete += 1
        return complete / len(KNOWN_OPERATORS)
