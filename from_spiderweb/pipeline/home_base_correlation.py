"""
HOME-BASE CORRELATION

Derives each aircraft's home base ("final resting spot") from the geographic
distribution of its takeoff and landing locations, maps that base to the
operator that controls the facility, and cross-correlates the fleet to surface
shared-space leads (craft that share an apron / base).

Why the resting spot matters
----------------------------
Altitude/speed/duration heuristics describe *what a craft is doing*; the place
it parks overnight describes *who owns it*. A facility has an operator, and the
craft that consistently sleeps there almost always belongs to (or is contracted
by) that operator. Two craft that share a base are operationally linked even
when their callsigns reveal nothing.

Reuses, rather than re-implements:
  - pipeline.gis_intelligence.PuertoRicoInfrastructure / haversine_nm
      → coordinate → operator-bearing facility lookup
  - pipeline.aircraft_intelligence.KNOWN_OPERATORS / AircraftProfile
      → confirmation signal and the shared profile schema
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pipeline.gis_intelligence import (
    InfrastructureFeature,
    InfrastructureType,
    PuertoRicoInfrastructure,
    haversine_nm,
)
from pipeline.aircraft_intelligence import (
    KNOWN_OPERATORS,
    AircraftProfile,
)


# ============================================================================
# OPERATOR → OWNER / MISSION TABLES
# ============================================================================

# Facility operators that do not, by themselves, identify an aircraft operator
# (a craft parked at an FAA field or a sea port could belong to anyone).
GENERIC_OPERATORS = {"", "FAA", "PSA", None}

# Facility operator → (canonical owner, primary mission deduced from the base).
OPERATOR_OWNER = {
    "USCG": "United States Coast Guard",
    "Puerto Rico Police": "Puerto Rico Police Department",
    "PREPA": "Puerto Rico Electric Power Authority",
    "US Navy": "United States Navy",
    "FAA": "Private / civil owner",
}

OPERATOR_MISSION = {
    "USCG": "Search & Rescue / Maritime Patrol",
    "Puerto Rico Police": "Law Enforcement",
    "PREPA": "Power Line Inspection",
    "US Navy": "Military Operations",
    "FAA": "Private Charter",
}

# Canonical home-base coordinate for each known craft, used as a fallback when
# the flight database carries no usable endpoint coordinates. Lets the fleet
# report render meaningfully even with an empty / absent DB.
KNOWN_OPERATOR_BASES = {
    "N5854Z": (18.4519, -66.1198),   # Isla Grande — PREPA rotor staging hub
    "C6062":  (18.4948, -67.1294),   # USCG Air Station Borinquen
    "N767PD": (18.4500, -66.0500),   # FURA base, San Juan metro
    "N684JB": (18.4519, -66.1198),   # Isla Grande — general-aviation apron
}

# Endpoint feature match radius. A home base is the field a craft is physically
# parked at, so this is deliberately tight (keeps neighbouring distinct bases —
# e.g. Isla Grande vs. the FURA base ~4 nm away — from bleeding together).
BASE_MATCH_RADIUS_NM = 3.0

# Proximity threshold for clustering endpoints into a single "spot".
CLUSTER_RADIUS_NM = 2.0


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class RestingSpot:
    """A clustered location where a craft begins/ends its operational days."""
    lat: float
    lon: float
    landings: int = 0
    takeoffs: int = 0
    overnight_count: int = 0       # first-of-day / last-of-day endpoints
    weight: float = 0.0            # dominance score used to pick the home base
    last_landing_time: str = ""
    nearest_feature_id: str = ""
    nearest_feature_name: str = ""
    nearest_operator: str = ""
    distance_nm: float = 0.0

    @property
    def is_resolved(self) -> bool:
        return bool(self.nearest_feature_id)


# ============================================================================
# HOME-BASE DEDUCER
# ============================================================================

class HomeBaseDeducer:
    """
    Derives a craft's home base from its takeoff/landing coordinates and maps
    it to an operator → owner → mission.
    """

    def __init__(self, db_path: str = str(Path.home() / "flight_database.db")):
        self.db_path = db_path
        self.infra = PuertoRicoInfrastructure()

    # -- endpoint extraction -------------------------------------------------

    def _endpoints(self, callsign: str) -> List[Tuple[float, float, str, str]]:
        """
        Return [(lat, lon, kind, iso_time)] for every usable takeoff/landing of
        the callsign. ``kind`` is "takeoff" or "landing". Missing coordinates
        (NULL / 0.0) are skipped. Returns [] gracefully if the DB/table absent.
        """
        rows: List[Tuple] = []
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT origin_lat, origin_lon, takeoff_time, "
                "       dest_lat, dest_lon, landing_time "
                "FROM flights WHERE callsign = ?",
                (callsign,),
            )
            rows = cur.fetchall()
            conn.close()
        except Exception:
            return []

        endpoints: List[Tuple[float, float, str, str]] = []
        for o_lat, o_lon, t_off, d_lat, d_lon, t_land in rows:
            if _usable(o_lat, o_lon):
                endpoints.append((o_lat, o_lon, "takeoff", t_off or ""))
            if _usable(d_lat, d_lon):
                endpoints.append((d_lat, d_lon, "landing", t_land or ""))
        return endpoints

    # -- clustering ----------------------------------------------------------

    def cluster_resting_spots(self, callsign: str) -> List[RestingSpot]:
        """
        Greedily cluster endpoints within CLUSTER_RADIUS_NM and weight each
        cluster. Endpoints that are the first or last event of their local day
        are treated as overnight markers (the craft slept there) and weighted
        higher. Returns spots sorted by descending weight (home base first).
        """
        endpoints = self._endpoints(callsign)

        # Fallback: no usable coordinates but a known canonical base.
        if not endpoints and callsign in KNOWN_OPERATOR_BASES:
            lat, lon = KNOWN_OPERATOR_BASES[callsign]
            spot = RestingSpot(lat=lat, lon=lon, landings=1, overnight_count=1,
                               weight=1.0)
            self._resolve_feature(spot)
            return [spot]

        if not endpoints:
            return []

        overnight = _overnight_endpoints(endpoints)

        clusters: List[Dict] = []
        for idx, (lat, lon, kind, ts) in enumerate(endpoints):
            target = None
            for c in clusters:
                if haversine_nm(c["lat"], c["lon"], lat, lon) <= CLUSTER_RADIUS_NM:
                    target = c
                    break
            if target is None:
                target = {"lat": lat, "lon": lon, "landings": 0, "takeoffs": 0,
                          "overnight": 0, "weight": 0.0, "last_landing": ""}
                clusters.append(target)

            w = 1.0
            if kind == "landing":
                target["landings"] += 1
                if ts > target["last_landing"]:
                    target["last_landing"] = ts
            else:
                target["takeoffs"] += 1
                w = 0.5  # mid-day takeoffs are weak home-base evidence
            if idx in overnight:
                target["overnight"] += 1
                w += 2.0
            target["weight"] += w

        spots: List[RestingSpot] = []
        for c in clusters:
            spot = RestingSpot(
                lat=c["lat"], lon=c["lon"],
                landings=c["landings"], takeoffs=c["takeoffs"],
                overnight_count=c["overnight"], weight=round(c["weight"], 2),
                last_landing_time=c["last_landing"],
            )
            self._resolve_feature(spot)
            spots.append(spot)

        spots.sort(key=lambda s: s.weight, reverse=True)
        return spots

    def home_base(self, callsign: str) -> Optional[RestingSpot]:
        spots = self.cluster_resting_spots(callsign)
        return spots[0] if spots else None

    # -- coordinate → operator ----------------------------------------------

    def _resolve_feature(self, spot: RestingSpot) -> None:
        feature = self.map_to_operator(spot.lat, spot.lon)
        if feature:
            spot.nearest_feature_id = feature.feature_id
            spot.nearest_feature_name = feature.name
            spot.nearest_operator = feature.operator
            spot.distance_nm = round(
                haversine_nm(spot.lat, spot.lon, feature.latitude, feature.longitude), 2
            )

    def map_to_operator(self, lat: float, lon: float) -> Optional[InfrastructureFeature]:
        """
        Nearest facility to (lat, lon), preferring a distinctive operator
        (USCG/PREPA/police/navy) over a generic field (FAA/port) at comparable
        range, since the distinctive operator is what identifies the craft.
        """
        nearby = self.infra.get_nearby_features(lat, lon, BASE_MATCH_RADIUS_NM)
        if not nearby:
            return None
        # get_nearby_features already returns nearest-first; promote the closest
        # distinctive-operator facility ahead of generic ones.
        distinctive = [f for f in nearby if f.operator not in GENERIC_OPERATORS]
        return distinctive[0] if distinctive else nearby[0]

    # -- profile fusion ------------------------------------------------------

    def deduce_profile(self, callsign: str) -> AircraftProfile:
        """
        Build an AircraftProfile by fusing the home-base operator signal with
        the KNOWN_OPERATORS confirmation. Records reasoning in
        ``operational_patterns['home_base_evidence']``.
        """
        spot = self.home_base(callsign)
        known = _known_for(callsign)
        evidence: List[str] = []

        profile = AircraftProfile(callsign=callsign, data_source="home_base")

        # Home-base derived O/O/M.
        hb_operator = spot.nearest_operator if spot else ""
        hb_distinctive = hb_operator and hb_operator not in GENERIC_OPERATORS
        if spot and spot.is_resolved:
            evidence.append(
                f"Home base resolved to {spot.nearest_feature_name} "
                f"({spot.distance_nm} nm, {spot.landings} landings / "
                f"{spot.overnight_count} overnight markers)"
            )

        if known:
            # Known operator is authoritative; home base confirms or conflicts.
            profile.owner = known["owner"]
            profile.operator = known["operator"]
            profile.aircraft_type = known["aircraft_type"]
            profile.primary_mission = known["primary_mission"]
            profile.secondary_missions = list(known["secondary_missions"])
            profile.operational_patterns = dict(known["operational_patterns"])
            profile.confidence_level = known["confidence_level"]
            profile.data_source = "known_db+home_base"

            if hb_distinctive and _agrees(hb_operator, known):
                profile.confidence_level = min(0.99, profile.confidence_level + 0.01)
                evidence.append(
                    f"Home-base operator '{hb_operator}' AGREES with known "
                    f"operator — corroborated."
                )
            elif hb_distinctive:
                evidence.append(
                    f"Home-base operator '{hb_operator}' CONFLICTS with known "
                    f"'{known['operator']}' — possible detachment, lease, or "
                    f"shared apron; flag for review."
                )
            elif spot and spot.is_resolved:
                evidence.append(
                    f"Home base is a shared/civil field ({spot.nearest_feature_name}); "
                    f"operator identity carried by known registry."
                )
        elif hb_distinctive:
            # Unknown craft: derive O/O/M purely from the home base.
            profile.operator = hb_operator
            profile.owner = OPERATOR_OWNER.get(hb_operator, hb_operator)
            profile.primary_mission = OPERATOR_MISSION.get(hb_operator, "Unknown")
            # Confidence scales with how dominant / overnight-anchored the base is.
            base = 0.55
            if spot.overnight_count:
                base += 0.15
            if spot.distance_nm <= 1.0:
                base += 0.10
            profile.confidence_level = round(min(0.9, base), 2)
            evidence.append(
                f"No registry entry; operator deduced from home base → "
                f"{profile.owner} / {profile.primary_mission}."
            )
        else:
            # Unknown craft at a generic field, or no location at all.
            if spot and spot.is_resolved:
                profile.operator = "Unknown (civil field)"
                profile.owner = "Private / civil owner"
                profile.primary_mission = "Private Charter"
                profile.confidence_level = 0.35
                evidence.append(
                    f"Home base is a generic civil field "
                    f"({spot.nearest_feature_name}); no operator attribution."
                )
            else:
                profile.primary_mission = "Unknown"
                profile.confidence_level = 0.15
                evidence.append("No usable takeoff/landing locations for this craft.")

        profile.operational_patterns = dict(profile.operational_patterns)
        profile.operational_patterns["home_base_evidence"] = evidence
        if spot and spot.is_resolved:
            profile.operational_patterns["home_base"] = spot.nearest_feature_name
        return profile

    def intelligence_report(self, callsign: str) -> str:
        """Human-readable home-base intelligence report for one craft."""
        profile = self.deduce_profile(callsign)
        spot = self.home_base(callsign)

        lines = [
            "═" * 70,
            f"  HOME-BASE INTELLIGENCE: {callsign}",
            "═" * 70,
            f"  Owner:            {profile.owner}",
            f"  Operator:         {profile.operator}",
            f"  Primary Mission:  {profile.primary_mission}",
            f"  Confidence:       {profile.confidence_level * 100:.0f}%",
            f"  Data Source:      {profile.data_source}",
            "",
        ]
        if spot and spot.is_resolved:
            lines += [
                "  FINAL RESTING SPOT",
                "  " + "─" * 50,
                f"  Facility:   {spot.nearest_feature_name} ({spot.nearest_feature_id})",
                f"  Operator:   {spot.nearest_operator}",
                f"  Position:   {spot.lat:.4f}, {spot.lon:.4f}  ({spot.distance_nm} nm from facility)",
                f"  Landings:   {spot.landings}   Takeoffs: {spot.takeoffs}   Overnight: {spot.overnight_count}",
                "",
            ]
        lines.append("  EVIDENCE")
        lines.append("  " + "─" * 50)
        for e in profile.operational_patterns.get("home_base_evidence", []):
            lines.append(f"  • {e}")
        lines.append("═" * 70)
        return "\n".join(lines)


# ============================================================================
# FLEET CO-LOCATION ANALYZER
# ============================================================================

class FleetColocationAnalyzer:
    """Cross-craft correlation: who shares a base with whom."""

    def __init__(self, db_path: str = str(Path.home() / "flight_database.db")):
        self.db_path = db_path
        self.deducer = HomeBaseDeducer(db_path)

    def _callsigns(self) -> List[str]:
        """Distinct callsigns in the DB, unioned with the known fleet."""
        found: List[str] = []
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT callsign FROM flights "
                "WHERE callsign IS NOT NULL AND callsign != ''"
            )
            found = [r[0] for r in cur.fetchall()]
            conn.close()
        except Exception:
            found = []
        for cs in KNOWN_OPERATORS:
            if cs not in found:
                found.append(cs)
        return sorted(found)

    def home_base_map(self) -> Dict[str, RestingSpot]:
        out: Dict[str, RestingSpot] = {}
        for cs in self._callsigns():
            spot = self.deducer.home_base(cs)
            if spot and spot.is_resolved:
                out[cs] = spot
        return out

    def shared_bases(self) -> Dict[str, List[str]]:
        """{feature_id: [callsigns]} for bases hosting ≥1 craft."""
        groups: Dict[str, List[str]] = defaultdict(list)
        for cs, spot in self.home_base_map().items():
            groups[spot.nearest_feature_id].append(cs)
        return {fid: sorted(cs) for fid, cs in groups.items()}

    def correlation_report(self) -> str:
        hb = self.home_base_map()
        groups = self.shared_bases()

        lines = [
            "# Fleet Home-Base Correlation",
            "",
            "## Per-craft home base",
            "",
            "| Callsign | Home base | Operator | Owner (deduced) | Mission |",
            "|----------|-----------|----------|-----------------|---------|",
        ]
        for cs in sorted(hb):
            spot = hb[cs]
            op = spot.nearest_operator or "—"
            owner = OPERATOR_OWNER.get(op, "—" if op in GENERIC_OPERATORS else op)
            mission = OPERATOR_MISSION.get(op, "—")
            lines.append(
                f"| {cs} | {spot.nearest_feature_name} | {op} | {owner} | {mission} |"
            )

        shared = {f: cs for f, cs in groups.items() if len(cs) >= 2}
        isolated = {f: cs for f, cs in groups.items() if len(cs) == 1}

        lines += ["", "## Shared-space leads", ""]
        if shared:
            for fid, crafts in sorted(shared.items()):
                ops = {hb[c].nearest_operator for c in crafts}
                kind = ("same-operator" if len(ops) == 1
                        else "CROSS-OPERATOR co-location")
                name = hb[crafts[0]].nearest_feature_name
                lines.append(
                    f"- **{name}** ({fid}) — {kind}: {', '.join(crafts)}. "
                    + ("Shared apron implies shared fuel/maintenance/ATC "
                       "relationships and a common operating tempo." if len(ops) == 1
                       else "Distinct operators sharing one field — a strong lead "
                            "for shared facilities or joint operations.")
                )
        else:
            lines.append("- No base hosts two or more craft in the current data.")

        lines += ["", "## Geographically isolated craft", ""]
        if isolated:
            for fid, crafts in sorted(isolated.items()):
                name = hb[crafts[0]].nearest_feature_name
                lines.append(f"- {crafts[0]} — sole occupant of {name} ({fid}).")
        else:
            lines.append("- None.")

        lines.append("")
        return "\n".join(lines)


# ============================================================================
# HELPERS
# ============================================================================

def _usable(lat, lon) -> bool:
    return (lat is not None and lon is not None
            and not (lat == 0.0 and lon == 0.0))


def _overnight_endpoints(endpoints: List[Tuple[float, float, str, str]]) -> set:
    """
    Indices of endpoints that are the first or last timestamped event of their
    local calendar day — i.e. the craft was parked there overnight.
    """
    by_day: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for idx, (_lat, _lon, _kind, ts) in enumerate(endpoints):
        if not ts:
            continue
        by_day[ts[:10]].append((ts, idx))
    overnight = set()
    for events in by_day.values():
        events.sort()
        overnight.add(events[0][1])    # first event of the day
        overnight.add(events[-1][1])   # last event of the day
    return overnight


def _known_for(callsign: str) -> Optional[Dict]:
    for key, data in KNOWN_OPERATORS.items():
        if key in callsign or callsign in key:
            return data
    return None


def _agrees(facility_operator: str, known: Dict) -> bool:
    """True if a facility operator string is consistent with a known record."""
    hay = f"{known['owner']} {known['operator']}".lower()
    op = facility_operator.lower()
    if op in hay:
        return True
    # Acronym / paraphrase matches.
    aliases = {
        "uscg": ["coast guard"],
        "puerto rico police": ["police", "fura"],
        "prepa": ["electric power", "prepa"],
        "us navy": ["navy"],
    }
    return any(a in hay for a in aliases.get(op, []))


# ============================================================================
# CLI ENTRY
# ============================================================================

if __name__ == "__main__":
    deducer = HomeBaseDeducer()
    for cs in ["N5854Z", "C6062", "N767PD", "N684JB"]:
        print(deducer.intelligence_report(cs))
        print()
    print(FleetColocationAnalyzer().correlation_report())
