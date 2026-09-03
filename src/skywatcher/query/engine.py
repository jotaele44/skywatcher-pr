"""Deterministic query engine over persisted CraftProfiles.

Resolves a prompt to one structured intent (+ optional craft/operator/time
slots) by keyword parsing — no LLM required — and answers it purely from the
committed profile artifacts. This is the sole source of truth the optional LLM
wrapper is allowed to phrase over.

Doctrine: never surfaces ``primary_mission`` as fact unless the profile marks it
authoritative (``data_source == known_db``); every answer carries the supporting
confidence grade, citations (profile field), and coverage gaps.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEFAULT_DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
DEFAULT_PROFILE_DIR = REPO / "profiles" / "craft"

_REG_RE = re.compile(r"\b[NC][0-9][0-9A-Z]{1,5}\b")

# Intent -> ordered keyword triggers (first match wins on scan order below).
_INTENT_KEYWORDS = [
    ("CO_OCCURRENCE", ("together", "co-occur", "cooccur", "same time", "alongside")),
    ("NEW_PATTERNS", ("new", "changed", "emerging", "recently started")),
    ("SCHEDULE", ("schedule", "when", "hours", "cadence", "what time", "day of week")),
    ("HOME_BASE", ("home base", "based", "home", "hangar")),
    ("PREFERRED_LZS", ("lz", "landing zone", "landing zones", "pad", "helipad", "land")),
    ("RECURRING_ROUTES", ("route", "recurring", "pattern", "corridor")),
    ("FLEET_SUMMARY", ("fleet", "how many", "list", "which aircraft", "who")),
]


@dataclass
class Answer:
    """Structured, grounded answer. ``to_text()`` renders it deterministically."""

    intent: str
    craft: str | None
    facts: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    confidence_grade: str = "INSUFFICIENT"
    coverage_gaps: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "craft": self.craft,
            "facts": self.facts,
            "citations": self.citations,
            "confidence_grade": self.confidence_grade,
            "coverage_gaps": self.coverage_gaps,
            "caveats": self.caveats,
        }

    def to_text(self) -> str:
        lines: list[str] = []
        if not self.facts:
            lines.append("Insufficient evidence in the current profiles to answer that.")
        else:
            lines.extend(f"• {f}" for f in self.facts)
        lines.append("")
        lines.append(f"Confidence: {self.confidence_grade} (review-gated candidate)")
        if self.coverage_gaps:
            lines.append(f"Coverage gaps: {', '.join(self.coverage_gaps)}")
        if self.caveats:
            lines.extend(f"Note: {c}" for c in self.caveats)
        if self.citations:
            srcs = sorted({c.get("source", "") for c in self.citations if c.get("source")})
            if srcs:
                lines.append(f"Sources: {', '.join(srcs)}")
        return "\n".join(lines)


# Doctrine caveat attached to any answer touching a non-authoritative mission.
_NO_INTENT_CAVEAT = (
    "Mission/intent is not inferred; only operator-declared missions are stated as fact."
)


class QueryEngine:
    """Loads CraftProfiles (DB-first, JSON fallback) and answers structured intents."""

    def __init__(
        self,
        db_path: Path | None = None,
        profile_dir: Path = DEFAULT_PROFILE_DIR,
    ):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB
        self.profile_dir = Path(profile_dir)
        self._profiles: dict[str, dict] | None = None

    # -- loading -----------------------------------------------------------

    def profiles(self) -> dict[str, dict]:
        if self._profiles is None:
            self._profiles = self._load()
        return self._profiles

    def _load(self) -> dict[str, dict]:
        db_profiles = self._load_from_db()
        if db_profiles:
            return db_profiles
        return self._load_from_json()

    def _load_from_db(self) -> dict[str, dict]:
        if not self.db_path.exists():
            return {}
        try:
            conn = sqlite3.connect(str(self.db_path))
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "craft_profiles" not in tables:
                conn.close()
                return {}
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM craft_profiles").fetchall()
            conn.close()
        except sqlite3.Error:
            return {}
        out: dict[str, dict] = {}
        for row in rows:
            out[row["registration"]] = _row_to_profile(dict(row))
        return out

    def _load_from_json(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        if not self.profile_dir.exists():
            return out
        for path in sorted(self.profile_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            reg = data.get("registration")
            if reg:
                out[reg] = data
        return out

    # -- parsing -----------------------------------------------------------

    def parse(self, prompt: str) -> dict:
        text = prompt.lower()
        reg_match = _REG_RE.search(prompt.upper())
        craft = reg_match.group(0) if reg_match else None
        if craft and craft not in self.profiles():
            # Not a known registration; treat as no craft slot.
            craft = None
        intent = "PROFILE"
        for name, kws in _INTENT_KEYWORDS:
            if any(k in text for k in kws):
                intent = name
                break
        operator = self._match_operator(text)
        time_slot = None
        if "this month" in text or "recent" in text or "new" in text:
            time_slot = "recent"
        return {"intent": intent, "craft": craft, "operator": operator, "time": time_slot}

    def _match_operator(self, text: str) -> str | None:
        for _reg, prof in self.profiles().items():
            op = (prof.get("operator") or "").lower()
            if op and op != "unknown" and op in text:
                return prof.get("operator")
        return None

    # -- answering ---------------------------------------------------------

    def answer(self, prompt: str) -> Answer:
        slots = self.parse(prompt)
        intent = slots["intent"]
        craft = slots["craft"]

        if intent in ("FLEET_SUMMARY", "CO_OCCURRENCE") or (
            not craft and intent in ("NEW_PATTERNS",)
        ):
            if intent == "CO_OCCURRENCE":
                return self._answer_co_occurrence()
            if intent == "NEW_PATTERNS":
                return self._answer_new_patterns_fleet()
            return self._answer_fleet_summary(slots["operator"])

        if not craft:
            # No craft resolved and not a fleet-level intent.
            return Answer(
                intent=intent,
                craft=None,
                facts=[],
                caveats=[
                    "Specify an aircraft registration (e.g. N5854Z) or ask a fleet-level question."
                ],
            )

        profile = self.profiles().get(craft)
        if not profile:
            return Answer(
                intent=intent, craft=craft, facts=[], caveats=[f"No profile for {craft}."]
            )

        handler = {
            "SCHEDULE": self._answer_schedule,
            "HOME_BASE": self._answer_home_base,
            "PREFERRED_LZS": self._answer_preferred_lzs,
            "RECURRING_ROUTES": self._answer_recurring_routes,
            "NEW_PATTERNS": self._answer_new_patterns,
            "PROFILE": self._answer_profile,
        }.get(intent, self._answer_profile)
        return handler(craft, profile)

    # -- per-craft handlers ------------------------------------------------

    def _cite(self, craft: str, field_name: str) -> dict:
        return {"source": f"craft_profiles/{craft}", "field": field_name}

    def _answer_schedule(self, craft: str, p: dict) -> Answer:
        sched = p.get("schedule") or {}
        cells = sched.get("dow_hour_cells") or []
        facts: list[str] = []
        if sched.get("operating_hours_summary"):
            facts.append(f"{craft}: {sched['operating_hours_summary']}.")
        for c in cells[:8]:
            facts.append(
                f"{c['dow']} {c['hour_bucket']}: ~{c['expected_per_week']} sightings/wk "
                f"({c['based_on_hits']} hits)."
            )
        return Answer(
            intent="SCHEDULE",
            craft=craft,
            facts=facts,
            citations=[self._cite(craft, "schedule")],
            confidence_grade=sched.get("confidence_grade", "INSUFFICIENT"),
            coverage_gaps=[g for g in p.get("coverage_gaps", []) if "schedule" in g],
            caveats=[] if cells else ["No cadence signal in the lookback window."],
        )

    def _answer_home_base(self, craft: str, p: dict) -> Answer:
        hb = p.get("home_base")
        if not hb:
            return Answer(
                intent="HOME_BASE",
                craft=craft,
                facts=[],
                coverage_gaps=[
                    g for g in p.get("coverage_gaps", []) if "base" in g or "origin" in g
                ],
                caveats=["No origin/destination endpoints resolved for this craft."],
            )
        name = hb.get("name") or hb.get("iata")
        facts = [
            f"{craft} home-base candidate: {name} "
            f"(origin x{hb.get('origin_count', 0)}, destination x{hb.get('destination_count', 0)}, "
            f"over {hb.get('eligible_periods_denominator')} eligible flight-days)."
        ]
        return Answer(
            intent="HOME_BASE",
            craft=craft,
            facts=facts,
            citations=[self._cite(craft, "home_base")],
            confidence_grade=hb.get("confidence_grade", "INSUFFICIENT"),
            coverage_gaps=[g for g in p.get("coverage_gaps", []) if "base" in g],
            caveats=_caps_to_caveats(hb.get("caps_applied", [])),
        )

    def _answer_preferred_lzs(self, craft: str, p: dict) -> Answer:
        lzs = p.get("preferred_lzs") or []
        facts = [
            f"{lz.get('name')} [{lz.get('lz_class')}]: {lz.get('hit_count')} landings "
            f"({lz.get('confidence_grade')})."
            for lz in lzs[:8]
        ]
        best = _best_grade([lz.get("confidence_grade", "INSUFFICIENT") for lz in lzs])
        return Answer(
            intent="PREFERRED_LZS",
            craft=craft,
            facts=facts,
            citations=[self._cite(craft, "preferred_lzs")],
            confidence_grade=best,
            caveats=[] if lzs else ["No landing-zone endpoints resolved."],
        )

    def _answer_recurring_routes(self, craft: str, p: dict) -> Answer:
        routes = p.get("recurring_routes") or []
        facts = [
            f"{r.get('route_pattern')} [{r.get('shape')}]: {r.get('n_observed')}x "
            f"over {r.get('denominator')} flight-days ({r.get('confidence_grade')})."
            for r in routes[:10]
        ]
        best = _best_grade([r.get("confidence_grade", "INSUFFICIENT") for r in routes])
        return Answer(
            intent="RECURRING_ROUTES",
            craft=craft,
            facts=facts,
            citations=[self._cite(craft, "recurring_routes")],
            confidence_grade=best,
            coverage_gaps=[g for g in p.get("coverage_gaps", []) if "route" in g],
            caveats=[] if routes else ["No routes met the recurrence threshold."],
        )

    def _answer_new_patterns(self, craft: str, p: dict) -> Answer:
        new = p.get("new_patterns") or []
        events = p.get("recurring_events") or []
        facts = [
            f"NEW: {n.get('route_pattern')} [{n.get('shape')}] x{n.get('n_observed')}." for n in new
        ]
        facts += [
            f"REINFORCED: {e.get('route_pattern')} now x{e.get('n_observed')} "
            f"(was x{e.get('n_observed_prior')})."
            for e in events
        ]
        return Answer(
            intent="NEW_PATTERNS",
            craft=craft,
            facts=facts,
            citations=[self._cite(craft, "new_patterns"), self._cite(craft, "recurring_events")],
            confidence_grade=_best_grade(
                [n.get("confidence_grade", "INSUFFICIENT") for n in new + events]
            ),
            caveats=[]
            if (new or events)
            else ["No new or reinforced patterns since the last build."],
        )

    def _answer_profile(self, craft: str, p: dict) -> Answer:
        facts = [
            f"{craft}: {p.get('aircraft_type') or 'type unknown'}, "
            f"operator {p.get('operator') or 'unknown'}, owner {p.get('owner') or 'unknown'} "
            f"(source: {p.get('data_source')})."
        ]
        if p.get("mission_is_authoritative") and p.get("primary_mission"):
            facts.append(f"Operator-declared mission: {p['primary_mission']}.")
        if p.get("home_base"):
            facts.append(f"Home-base candidate: {p['home_base'].get('name')}.")
        facts.append(
            f"{p.get('total_observations', 0)} observations, "
            f"{len(p.get('recurring_routes') or [])} recurring routes, "
            f"last seen {p.get('last_seen') or 'n/a'}."
        )
        caveats = [] if p.get("mission_is_authoritative") else [_NO_INTENT_CAVEAT]
        return Answer(
            intent="PROFILE",
            craft=craft,
            facts=facts,
            citations=[self._cite(craft, "*")],
            confidence_grade=p.get("profile_confidence_grade", "INSUFFICIENT"),
            coverage_gaps=p.get("coverage_gaps", []),
            caveats=caveats,
        )

    # -- fleet-level handlers ---------------------------------------------

    def _answer_fleet_summary(self, operator: str | None) -> Answer:
        profs = list(self.profiles().values())
        if operator:
            profs = [p for p in profs if (p.get("operator") or "") == operator]
        facts = [f"{len(profs)} aircraft profiled" + (f" for {operator}" if operator else "") + "."]
        for p in sorted(profs, key=lambda x: -(x.get("total_observations") or 0))[:15]:
            facts.append(
                f"{p['registration']}: {p.get('aircraft_type') or '?'}, "
                f"{p.get('total_observations', 0)} obs, grade {p.get('profile_confidence_grade')}."
            )
        return Answer(
            intent="FLEET_SUMMARY",
            craft=None,
            facts=facts,
            citations=[{"source": "craft_profiles", "field": "*"}],
            confidence_grade=_best_grade(
                [p.get("profile_confidence_grade", "INSUFFICIENT") for p in profs]
            ),
        )

    def _answer_new_patterns_fleet(self) -> Answer:
        facts: list[str] = []
        for reg, p in self.profiles().items():
            for n in p.get("new_patterns") or []:
                facts.append(f"{reg}: NEW {n.get('route_pattern')} x{n.get('n_observed')}.")
        return Answer(
            intent="NEW_PATTERNS",
            craft=None,
            facts=facts,
            citations=[{"source": "craft_profiles", "field": "new_patterns"}],
            confidence_grade="MODERATE" if facts else "INSUFFICIENT",
            caveats=[] if facts else ["No new patterns across the fleet since the last build."],
        )

    def _answer_co_occurrence(self) -> Answer:
        # Co-occurrence is derived elsewhere (rlsm_network_graph); profiles don't
        # carry it yet. Report honestly rather than guess.
        return Answer(
            intent="CO_OCCURRENCE",
            craft=None,
            facts=[],
            caveats=[
                "Co-occurrence is not part of the per-craft profile yet; "
                "run scripts/rlsm_network_graph.py for pairwise co-occurrence."
            ],
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_GRADE_ORDER = ["INSUFFICIENT", "LOW", "MODERATE", "HIGH", "VERIFIED"]

_JSON_FIELDS = [
    "home_base",
    "preferred_lzs",
    "schedule",
    "recurring_routes",
    "recurring_events",
    "new_patterns",
    "coverage_gaps",
    "caps_applied",
    "secondary_missions",
]


def _best_grade(grades: list[str]) -> str:
    best = "INSUFFICIENT"
    for g in grades:
        if g in _GRADE_ORDER and _GRADE_ORDER.index(g) > _GRADE_ORDER.index(best):
            best = g
    return best


def _caps_to_caveats(caps: list[str]) -> list[str]:
    mapping = {
        "no_georef_spatial_capped": "Spatial claim capped (no georeferenced positions).",
        "no_denominator_recurrence_capped_below_high": "Recurrence capped (no eligible-period denominator).",
        "no_source_context_capped": "Capped (no source/receiver context).",
    }
    return [mapping.get(c, c) for c in (caps or [])]


def _row_to_profile(row: dict) -> dict:
    """Rehydrate JSON columns from a craft_profiles DB row into a profile dict."""
    out = dict(row)
    for f in _JSON_FIELDS:
        if isinstance(out.get(f), str):
            try:
                out[f] = json.loads(out[f])
            except (ValueError, TypeError):
                out[f] = None
    out["mission_is_authoritative"] = bool(out.get("mission_is_authoritative"))
    out["is_stale"] = bool(out.get("is_stale"))
    return out
