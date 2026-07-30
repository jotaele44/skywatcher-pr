"""FPIM CraftProfile — consolidated, continuously-enrichable per-aircraft profile.

Aggregates identity, home base, preferred landing zones, empirical schedule,
recurring routes, and newly-surfaced patterns for one registration from the
RLSM corpus, reusing the FPIM analytic cores (``schedule``, ``route_recurrence``,
``endpoint_matcher``) and the Core registries — without reinventing any of them.

Doctrine (docs/MODULE_SPEC_FPIM.md, skywatcher-airspace-evidence skill):
  * No intent/mission inference. ``primary_mission`` is authoritative only for
    ``data_source == known_db`` (operator-declared); it is never guessed here.
    The aircraft-type-to-mission fallback in ``aircraft_profile`` is deliberately
    NOT used on the deduced path.
  * Every aggregate is a review-gated candidate carrying a confidence grade,
    evidence tier, and eligible-period denominator.
  * Label independence: every registration is aggregated identically; no label
    gates whether a craft is profiled.

Core+FPIM imports only. Persists to a ``craft_profiles`` table (incremental
upsert) and schema-valid JSON under ``profiles/craft/<reg>.json``.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from skywatcher.core.confidence import GRADES, float_to_grade, grade
from skywatcher.core.known_operators import KNOWN_OPERATORS
from skywatcher.core.normalize_locations import load_simple_yaml
from skywatcher.fpim.aircraft_profile import CALLSIGN_PREFIXES
from skywatcher.fpim.route_recurrence import craft_routes_and_base
from skywatcher.fpim.schedule import craft_schedule, parse_ts

REPO = Path(__file__).resolve().parents[3]
DEFAULT_DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
DEFAULT_PROFILE_DIR = REPO / "profiles" / "craft"
CONFIGS = REPO / "configs"
STALE_THRESHOLD_DAYS = 30


# ---------------------------------------------------------------------------
# Registry indexes (ground-truth reference data)
# ---------------------------------------------------------------------------

def load_airport_index(config_dir: Path = CONFIGS) -> Dict[str, dict]:
    """IATA/ICAO code -> {airport_id, canonical_name, lat, lon}."""
    data = load_simple_yaml(config_dir / "airport_registry.yaml")
    index: Dict[str, dict] = {}
    for ap in data.get("airports", []) or []:
        entry = {
            "airport_id": ap.get("airport_id"),
            "canonical_name": ap.get("canonical_name"),
            "lat": ap.get("lat"),
            "lon": ap.get("lon"),
        }
        for code in (ap.get("iata"), ap.get("icao")):
            if code:
                index[str(code).upper()] = entry
    return index


def load_lz_class_index(config_dir: Path = CONFIGS) -> Dict[str, str]:
    """airport_id -> lz_class for known LZ candidates (ground truth)."""
    data = load_simple_yaml(config_dir / "lz_registry.yaml")
    index: Dict[str, str] = {}
    for lz in data.get("known_lz_candidates", []) or []:
        aid = lz.get("airport_id")
        if aid:
            index[aid] = lz.get("lz_class", "UNKNOWN_LZ")
    return index


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------

@dataclass
class CraftProfile:
    registration: str
    callsign: Optional[str] = None
    aircraft_type: Optional[str] = None
    owner: Optional[str] = None
    operator: Optional[str] = None
    country: Optional[str] = None
    data_source: str = "unknown"
    primary_mission: Optional[str] = None
    mission_is_authoritative: bool = False
    secondary_missions: List[str] = field(default_factory=list)
    home_base: Optional[dict] = None
    preferred_lzs: List[dict] = field(default_factory=list)
    schedule: Optional[dict] = None
    recurring_routes: List[dict] = field(default_factory=list)
    recurring_events: List[dict] = field(default_factory=list)
    new_patterns: List[dict] = field(default_factory=list)
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    total_observations: int = 0
    is_stale: bool = True
    confidence_level: float = 0.0
    profile_confidence_grade: str = "INSUFFICIENT"
    coverage_gaps: List[str] = field(default_factory=list)
    caps_applied: List[str] = field(default_factory=list)
    source_baseline: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class CraftProfileBuilder:
    """Builds/enriches CraftProfiles from the RLSM corpus.

    Idempotent: re-running recomputes aggregates and bumps activity from the
    current corpus state. Degrades gracefully when the DB or optional columns
    are absent.
    """

    def __init__(self, db_path: Path = DEFAULT_DB, config_dir: Path = CONFIGS):
        self.db_path = Path(db_path)
        self.config_dir = Path(config_dir)
        self.airport_index = load_airport_index(config_dir)
        self.lz_class_index = load_lz_class_index(config_dir)

    # -- public API --------------------------------------------------------

    def registrations(self, conn: sqlite3.Connection) -> List[str]:
        rows = conn.execute(
            """
            SELECT DISTINCT registration FROM aircraft_observations
            WHERE registration IS NOT NULL AND TRIM(registration) != ''
            ORDER BY registration
            """
        ).fetchall()
        return [r[0] for r in rows]

    def build_all(self, conn: sqlite3.Connection) -> List[CraftProfile]:
        baseline = self._source_baseline(conn)
        return [self.build_one(conn, reg, baseline) for reg in self.registrations(conn)]

    def build_one(
        self,
        conn: sqlite3.Connection,
        registration: str,
        source_baseline: Optional[str] = None,
    ) -> CraftProfile:
        baseline = source_baseline or self._source_baseline(conn)
        profile = CraftProfile(
            registration=registration,
            source_baseline=baseline,
            generated_at=datetime.utcnow().isoformat(timespec="seconds"),
        )

        self._resolve_identity(conn, profile)
        self._resolve_activity(conn, profile)

        has_georef = self._has_georef(conn, registration)
        routes_base = craft_routes_and_base(conn, registration)
        self._resolve_home_base(profile, routes_base, has_georef)
        self._resolve_preferred_lzs(profile, routes_base, has_georef)
        self._resolve_recurring_routes(profile, routes_base)
        self._resolve_schedule(conn, profile)
        self._resolve_patterns(conn, profile)
        self._finalize(profile, routes_base)
        return profile

    # -- identity ----------------------------------------------------------

    def _resolve_identity(self, conn: sqlite3.Connection, p: CraftProfile) -> None:
        # 1) Operator-declared ground truth (KNOWN_OPERATORS, substring match).
        known = self._match_known_operator(p.registration)
        if known:
            p.owner = known.get("owner")
            p.operator = known.get("operator")
            p.aircraft_type = known.get("aircraft_type")
            p.primary_mission = known.get("primary_mission")
            p.secondary_missions = list(known.get("secondary_missions", []))
            p.mission_is_authoritative = True
            p.data_source = "known_db"
        else:
            p.data_source = "deduced"
            # NB: no mission inference on the deduced path (doctrine).

        # 2) Observed fields from the corpus (fill gaps, never overwrite truth).
        obs = conn.execute(
            """
            SELECT aircraft_type, operator_text, callsign
            FROM aircraft_observations
            WHERE registration = ?
              AND (aircraft_type IS NOT NULL OR operator_text IS NOT NULL OR callsign IS NOT NULL)
            """,
            (p.registration,),
        ).fetchall()
        p.aircraft_type = p.aircraft_type or _most_common([r[0] for r in obs])
        p.operator = p.operator or _most_common([r[1] for r in obs])
        p.callsign = _most_common([r[2] for r in obs]) or p.callsign

        # 3) FAA registry owner (ground truth) if still unknown.
        if not p.owner:
            faa = conn.execute(
                "SELECT name, manufacturer, model FROM aircraft_registry WHERE n_number = ?",
                (p.registration,),
            ).fetchone()
            if faa:
                p.owner = faa[0] or p.owner
                if not p.aircraft_type and (faa[1] or faa[2]):
                    p.aircraft_type = " ".join(x for x in (faa[1], faa[2]) if x)
                p.data_source = "db_history" if p.data_source == "deduced" else p.data_source

        # 4) Country from callsign/registration prefix.
        for prefix, info in CALLSIGN_PREFIXES.items():
            if p.registration.startswith(prefix):
                p.country = info["country"]
                break

    @staticmethod
    def _match_known_operator(registration: str) -> Optional[dict]:
        for key, data in KNOWN_OPERATORS.items():
            if key in registration or registration in key:
                return data
        return None

    # -- activity ----------------------------------------------------------

    def _resolve_activity(self, conn: sqlite3.Connection, p: CraftProfile) -> None:
        expr = _ts_expr(conn)
        row = conn.execute(
            f"""
            SELECT COUNT(*), MIN({expr}), MAX({expr})
            FROM aircraft_observations a JOIN screenshots s USING(screenshot_id)
            WHERE a.registration = ?
            """,
            (p.registration,),
        ).fetchone()
        if row and row[0]:
            p.total_observations = row[0]
            p.first_seen = row[1] or ""
            p.last_seen = row[2] or ""
        p.is_stale = self._is_stale(p.last_seen)

    @staticmethod
    def _is_stale(last_seen: Optional[str]) -> bool:
        dt = parse_ts(last_seen) if last_seen else None
        if dt is None:
            return True
        ref = datetime.utcnow()
        if dt.tzinfo is not None:
            ref = ref.replace(tzinfo=dt.tzinfo)
        return (ref - dt).days > STALE_THRESHOLD_DAYS

    def _has_georef(self, conn: sqlite3.Connection, registration: str) -> bool:
        row = conn.execute(
            """
            SELECT COUNT(*) FROM geo_anchors ga
            JOIN aircraft_observations a USING(screenshot_id)
            WHERE a.registration = ? AND ga.lat IS NOT NULL AND ga.lon IS NOT NULL
            """,
            (registration,),
        ).fetchone()
        return bool(row and row[0])

    # -- home base ---------------------------------------------------------

    def _resolve_home_base(self, p: CraftProfile, routes_base: dict, has_georef: bool) -> None:
        origins = routes_base.get("origin_counts", {})
        dests = routes_base.get("destination_counts", {})
        denom = routes_base.get("eligible_flight_days") or 0
        combined: Dict[str, int] = {}
        for code, n in {**origins}.items():
            combined[code] = combined.get(code, 0) + n
        for code, n in dests.items():
            combined[code] = combined.get(code, 0) + n
        if not combined:
            p.coverage_gaps.append("no_origin_destination_side_mining")
            return

        top_code = max(combined, key=combined.get)
        facility = self.airport_index.get(top_code.upper(), {})
        g = grade(
            observation_count=combined[top_code],
            denominator=denom or None,
            is_spatial=True,
            has_georef=has_georef,
        )
        p.home_base = {
            "facility_id": facility.get("airport_id"),
            "name": facility.get("canonical_name"),
            "iata": top_code,
            "origin_count": origins.get(top_code, 0),
            "destination_count": dests.get(top_code, 0),
            "eligible_periods_denominator": denom or None,
            "review_status": "candidate",
            **g.as_dict(),
        }
        if not has_georef:
            p.coverage_gaps.append("home_base_no_georef")

    # -- preferred LZs -----------------------------------------------------

    def _resolve_preferred_lzs(self, p: CraftProfile, routes_base: dict, has_georef: bool) -> None:
        dests = routes_base.get("destination_counts", {})
        denom = routes_base.get("eligible_flight_days") or 0
        lzs: List[dict] = []
        for code, n in sorted(dests.items(), key=lambda kv: -kv[1]):
            facility = self.airport_index.get(code.upper(), {})
            aid = facility.get("airport_id")
            lz_class = self.lz_class_index.get(aid, "AIRPORT") if aid else "AIRPORT"
            g = grade(
                observation_count=n,
                denominator=denom or None,
                is_spatial=True,
                has_georef=has_georef,
            )
            lzs.append({
                "facility_id": aid,
                "lz_class": lz_class,
                "name": facility.get("canonical_name") or code,
                "hit_count": n,
                "eligible_periods_denominator": denom or None,
                "review_status": "candidate",
                **g.as_dict(),
            })
        p.preferred_lzs = lzs

    # -- recurring routes --------------------------------------------------

    def _resolve_recurring_routes(self, p: CraftProfile, routes_base: dict) -> None:
        routes: List[dict] = []
        for r in routes_base.get("recurring_routes", []):
            denom = r.get("denominator") or 0
            g = grade(observation_count=r.get("n_observed", 0), denominator=denom or None)
            routes.append({**r, "review_status": "candidate", **g.as_dict()})
        p.recurring_routes = routes
        if not routes:
            p.coverage_gaps.append("no_recurring_routes")

    # -- schedule ----------------------------------------------------------

    def _resolve_schedule(self, conn: sqlite3.Connection, p: CraftProfile) -> None:
        sched = craft_schedule(conn, p.registration)
        cells = sched.get("dow_hour_cells", [])
        total_hits = sum(c.get("based_on_hits", 0) for c in cells)
        g = grade(
            observation_count=total_hits,
            denominator=sched.get("denominator") or None,
        )
        sched.update({"review_status": "candidate", **g.as_dict()})
        p.schedule = sched
        if not cells:
            p.coverage_gaps.append("no_schedule_signal")

    # -- pattern diff ------------------------------------------------------

    def _resolve_patterns(self, conn: sqlite3.Connection, p: CraftProfile) -> None:
        prior = self._load_prior_snapshot(conn, p.registration)
        prior_routes = {r["route_pattern"] for r in prior.get("recurring_routes", [])}
        prior_counts = {r["route_pattern"]: r.get("n_observed", 0)
                        for r in prior.get("recurring_routes", [])}

        new_patterns: List[dict] = []
        recurring_events: List[dict] = []
        for r in p.recurring_routes:
            pat = r["route_pattern"]
            if pat not in prior_routes:
                new_patterns.append({
                    "kind": "new_recurring_route",
                    "route_pattern": pat,
                    "shape": r.get("shape"),
                    "n_observed": r.get("n_observed"),
                    "review_status": "candidate",
                    "confidence_grade": r.get("confidence_grade"),
                    "evidence_tier": r.get("evidence_tier"),
                })
            elif r.get("n_observed", 0) > prior_counts.get(pat, 0):
                recurring_events.append({
                    "kind": "route_reinforced",
                    "route_pattern": pat,
                    "n_observed": r.get("n_observed"),
                    "n_observed_prior": prior_counts.get(pat, 0),
                    "review_status": "candidate",
                    "confidence_grade": r.get("confidence_grade"),
                    "evidence_tier": r.get("evidence_tier"),
                })
        p.new_patterns = new_patterns
        p.recurring_events = recurring_events

    # -- finalize ----------------------------------------------------------

    def _finalize(self, p: CraftProfile, routes_base: dict) -> None:
        grades = [g["confidence_grade"] for g in (
            [p.home_base] if p.home_base else []
        ) + p.recurring_routes + ([p.schedule] if p.schedule else [])
            if isinstance(g, dict) and g.get("confidence_grade")]
        caps: List[str] = []
        for src in ([p.home_base, p.schedule] + p.recurring_routes + p.preferred_lzs):
            if isinstance(src, dict):
                caps.extend(src.get("caps_applied", []) or [])
        p.caps_applied = sorted(set(caps))

        if p.data_source == "known_db":
            p.profile_confidence_grade = "VERIFIED"
        elif grades:
            # Strongest supporting aggregate, but never above HIGH for deduced.
            best = max(grades, key=lambda g: GRADES.index(g))
            if GRADES.index(best) > GRADES.index("HIGH"):
                best = "HIGH"
            p.profile_confidence_grade = best
        else:
            p.profile_confidence_grade = "INSUFFICIENT"
        p.confidence_level = _grade_float(p.profile_confidence_grade)

    # -- persistence helpers ----------------------------------------------

    def _source_baseline(self, conn: sqlite3.Connection) -> str:
        expr = _ts_expr(conn)
        row = conn.execute(
            f"SELECT MAX({expr}) FROM aircraft_observations a JOIN screenshots s USING(screenshot_id)"
        ).fetchone()
        max_ts = row[0] if row else None
        return f"rlsm@max_ts={max_ts or 'none'}"

    def _load_prior_snapshot(self, conn: sqlite3.Connection, registration: str) -> dict:
        try:
            row = conn.execute(
                """
                SELECT recurring_routes_json FROM profile_snapshots
                WHERE registration = ? ORDER BY taken_at DESC LIMIT 1
                """,
                (registration,),
            ).fetchone()
        except sqlite3.OperationalError:
            return {}
        if not row or not row[0]:
            return {}
        try:
            return {"recurring_routes": json.loads(row[0])}
        except (ValueError, TypeError):
            return {}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _most_common(values: List[Optional[str]]) -> Optional[str]:
    from collections import Counter
    cleaned = [v for v in values if v]
    if not cleaned:
        return None
    return Counter(cleaned).most_common(1)[0][0]


def _ts_expr(conn: sqlite3.Connection) -> str:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(screenshots)")}
    if "true_flight_ts" in cols:
        return "COALESCE(s.true_flight_ts, s.filename_ts)"
    return "s.filename_ts"


def _grade_float(g: str) -> float:
    from skywatcher.core.confidence import grade_to_float
    return grade_to_float(g)


# ---------------------------------------------------------------------------
# Persistence (DB table + JSON export + snapshots)
# ---------------------------------------------------------------------------

_JSON_COLUMNS = [
    "home_base", "preferred_lzs", "schedule", "recurring_routes",
    "recurring_events", "new_patterns", "coverage_gaps", "caps_applied",
    "secondary_missions",
]


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS craft_profiles (
            registration      TEXT PRIMARY KEY,
            callsign          TEXT,
            aircraft_type     TEXT,
            owner             TEXT,
            operator          TEXT,
            country           TEXT,
            data_source       TEXT NOT NULL,
            primary_mission   TEXT,
            mission_is_authoritative INTEGER NOT NULL DEFAULT 0,
            secondary_missions TEXT,
            home_base         TEXT,
            preferred_lzs     TEXT,
            schedule          TEXT,
            recurring_routes  TEXT,
            recurring_events  TEXT,
            new_patterns      TEXT,
            first_seen        TEXT,
            last_seen         TEXT,
            total_observations INTEGER NOT NULL DEFAULT 0,
            is_stale          INTEGER NOT NULL DEFAULT 1,
            confidence_level  REAL,
            profile_confidence_grade TEXT,
            coverage_gaps     TEXT,
            caps_applied      TEXT,
            source_baseline   TEXT,
            generated_at      TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS profile_snapshots (
            registration TEXT NOT NULL,
            taken_at     TEXT NOT NULL,
            recurring_routes_json TEXT,
            schedule_json TEXT,
            PRIMARY KEY (registration, taken_at)
        );
        """
    )


def upsert_profile(conn: sqlite3.Connection, profile: CraftProfile) -> None:
    d = profile.to_dict()
    row = dict(d)
    for col in _JSON_COLUMNS:
        row[col] = json.dumps(d.get(col))
    row["mission_is_authoritative"] = int(bool(d["mission_is_authoritative"]))
    row["is_stale"] = int(bool(d["is_stale"]))
    cols = [
        "registration", "callsign", "aircraft_type", "owner", "operator", "country",
        "data_source", "primary_mission", "mission_is_authoritative", "secondary_missions",
        "home_base", "preferred_lzs", "schedule", "recurring_routes", "recurring_events",
        "new_patterns", "first_seen", "last_seen", "total_observations", "is_stale",
        "confidence_level", "profile_confidence_grade", "coverage_gaps", "caps_applied",
        "source_baseline", "generated_at",
    ]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "registration")
    conn.execute(
        f"INSERT INTO craft_profiles ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(registration) DO UPDATE SET {updates}",
        [row[c] for c in cols],
    )


def write_snapshot(conn: sqlite3.Connection, profile: CraftProfile) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO profile_snapshots (registration, taken_at, "
        "recurring_routes_json, schedule_json) VALUES (?, ?, ?, ?)",
        (
            profile.registration,
            profile.generated_at,
            json.dumps(profile.recurring_routes),
            json.dumps(profile.schedule),
        ),
    )


def write_json(profile: CraftProfile, out_dir: Path = DEFAULT_PROFILE_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{profile.registration}.json"
    path.write_text(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path
