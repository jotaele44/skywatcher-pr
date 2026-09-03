"""
GNIS-backed place-name gazetteer for RLSM screenshot label extraction.

Replaces the 91-name inline vocabulary that used to live in
``fr24/rlsm_extractors.py`` (77 municipios + 10 airport entries + a handful of
territories and water bodies). ``data/reference/Gazetteer_PR_GNIS.gpkg`` has
been in the repo all along — 5,817 Puerto Rico features, 5,039 distinct
normalized names — but was only wired into ``fr24/zone_label_harvest.py`` and
``pipeline/normalize_locations.py``, never into the screenshot extractor.

Anything below municipio resolution used to be invisible: no barrios, no
El Yunque, no Cordillera Central, no Bahía de San Juan, no Caño Martín Peña,
no Mona/Desecheo/Caja de Muertos. All of it is in GNIS.

This module does not re-implement the GeoPackage read. ``zone_label_harvest``
already opens it with plain ``sqlite3`` (a GeoPackage *is* a SQLite file, so no
fiona/geopandas dependency) and already ships a correct ``unicodedata`` NFKD
accent fold. We reuse both:

  - ``load_registry()``  → GNIS rows + landing-zone/military ICAO codes
  - ``_norm()``          → NFKD fold; handles Ü, which the old ``_ascii_fold``
                           missed (the ``MAYAGÜEZ`` bug that
                           ``scripts/rlsm_diacritic_repoi.py`` was patching
                           after the fact instead of at the source)

Matching is over **token n-grams with word boundaries**, not the old
``if key in text_upper`` substring scan — so "SEAWORLD" no longer matches the
GNIS feature class "Sea", and a Tier-1 hit reports the exact token span it
consumed so the caller can suppress the duplicate Tier-2 emission.

Confidence is tiered by GNIS ``feature_class`` rather than being the constant
``min(0.90, 0.70)`` the old classifier returned for every vocabulary hit.

Loading costs ~0.1 s, so there is no cache file — call it per process.

CLI (inspection):
    python3 -m fr24.rlsm_gazetteer --stats
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from fr24.zone_label_harvest import (  # noqa: E402
    _norm,
    _strip_generic,
    load_registry,
)

# Longest n-gram we will try to match. "Eugenio Maria de Hostos" is 4 tokens;
# nothing useful in the corpus runs longer than that on one map label.
MAX_GRAM = 4

# Normalized keys shorter than this are never matched. In PR GNIS this excludes
# exactly two names ("rio", "tio"), so it costs almost no recall while removing
# the whole class of 2-3 letter false positives.
MIN_KEY_LEN = 4

# GNIS feature classes worth high confidence: these are the things FR24 actually
# renders as map labels.
CLASS_TIER_HIGH = {
    "Populated Place", "Civil", "Census", "Military", "Airport", "Locale",
}

# Terrain / hydrography. Real labels on a zoomed-out frame (Cordillera Central,
# Bahía de San Juan, Isla de Mona) but a weaker signal than a populated place,
# because the names are longer and OCR mangles them more often.
CLASS_TIER_GEO = {
    "Summit", "Range", "Ridge", "Cliff", "Gap", "Valley", "Basin", "Flat",
    "Plain", "Woods", "Area",
    "Bay", "Stream", "Lake", "Reservoir", "Channel", "Canal", "Sea", "Falls",
    "Spring", "Swamp", "Gut",
    "Island", "Cape", "Beach", "Bar",
}

BASE_CONF_HIGH = 0.85
BASE_CONF_GEO = 0.65
BASE_CONF_LOW = 0.50
BASE_CONF_ANCHOR = 0.92   # static ICAO anchors — exact codes, no ambiguity

# GNIS feature_class → the pin_type_guess vocabulary in data/rlsm/schema.sql.
CLASS_TO_PIN_TYPE = {
    "Populated Place": "municipality",
    "Civil":           "municipality",
    "Census":          "municipality",
    "Military":        "military",
    "Airport":         "airport",
    "Locale":          "locale",
    "Summit":          "mountain",
    "Range":           "mountain",
    "Ridge":           "mountain",
    "Cliff":           "mountain",
    "Gap":             "mountain",
    "Valley":          "terrain",
    "Basin":           "terrain",
    "Flat":            "terrain",
    "Plain":           "terrain",
    "Woods":           "terrain",
    "Area":            "terrain",
    "Bay":             "water",
    "Stream":          "water",
    "Lake":            "water",
    "Reservoir":       "water",
    "Channel":         "water",
    "Canal":           "water",
    "Sea":             "water",
    "Falls":           "water",
    "Spring":          "water",
    "Swamp":           "water",
    "Gut":             "water",
    "Island":          "coastal",
    "Cape":            "coastal",
    "Beach":           "coastal",
    "Bar":             "coastal",
}

# Generic Spanish words that are ALSO standalone GNIS populated-place names in
# Puerto Rico. Determined by intersecting the GNIS key set with a generic-word
# list, not guessed: these four are the entire overlap at >=4 chars.
#
# They are rejected only as *single-token* matches. A longer n-gram containing
# them ("Sabana Grande", "Bahia de San Juan") still matches normally, which is
# the behaviour we want.
AMBIGUOUS_SINGLE_TOKENS = {"bahia", "mora", "sabana", "nuevo", "nueva"}

# FR24 / iOS chrome that Tesseract reads off every frame. Dropped before
# matching so it can never reach Tier 2 and become an unknown_label_candidate.
# The "®fli htradar24 ©" debris that was polluting the review queue lives here.
CHROME_TOKENS = {
    "flightradar", "flightradar24", "htradar24", "radar24", "fli",
    "route", "follow", "more", "info", "playback", "share", "filter",
    "search", "settings", "terms", "privacy", "legal", "google", "apple",
    "altitude", "speed", "barometric", "ground", "view", "track",
    "arrived", "departed", "landed", "estimated", "scheduled", "delayed",
    "available", "aircraft", "flight", "live", "satellite", "hybrid",
    "reg", "type", "from", "dest", "origin", "eta", "std", "atd", "sta",
}

# Static ICAO anchors. GNIS carries the airports as named features but not
# their ICAO codes, and FR24 labels them by code.
STATIC_ANCHORS: list[tuple[str, str, float, float]] = [
    ("TJSJ", "Luis Muñoz Marín International Airport", 18.4394, -66.0018),
    ("TJIG", "Fernando Luis Ribas Dominicci Airport",  18.4567, -66.0982),
    ("TJBQ", "Rafael Hernández Airport",               18.4949, -67.1294),
    ("TJMZ", "Eugenio María de Hostos Airport",        18.2556, -67.1485),
    ("TJNR", "José Aponte de la Torre Airport",        18.2453, -65.6436),
    ("TJPS", "Mercedita Airport",                      18.0083, -66.5630),
    ("TJVQ", "Antonio Rivera Rodríguez Airport",       18.1348, -65.4936),
    ("TJCP", "Benjamín Rivera Noriega Airport",        18.3129, -65.3044),
]

# Off-island features that appear on a zoomed-out FR24 frame but are outside the
# PR GNIS extract. Small and deliberately so — the review queue surfaces the
# rest as unknowns for later promotion.
REGIONAL_EXTRAS: list[tuple[str, str]] = [
    ("Caribbean Sea",       "water"),
    ("Atlantic Ocean",      "water"),
    ("Mona Passage",        "water"),
    ("Vieques Sound",       "water"),
    ("Dominican Republic",  "territory"),
    ("Saint Thomas",        "territory"),
    ("Saint Croix",         "territory"),
    ("Saint John",          "territory"),
    ("Tortola",             "territory"),
    ("Virgin Gorda",        "territory"),
    ("Anegada",             "territory"),
    ("Saint Martin",        "territory"),
    ("Anguilla",            "territory"),
    ("Saba",                "territory"),
    ("US Virgin Islands",   "territory"),
    ("British Virgin Islands", "territory"),
]


class Gazetteer:
    """Normalized-key place-name index with n-gram span matching."""

    def __init__(self, entries: dict[str, dict]) -> None:
        self.entries = entries
        self._max_gram = MAX_GRAM

    # -- lookup -------------------------------------------------------------

    def get(self, key: str) -> dict | None:
        return self.entries.get(key)

    def lookup(self, text: str) -> dict | None:
        """Resolve a free-text label (e.g. 'MAYAGÜEZ' or 'Mayaguez')."""
        n = _norm(text)
        hit = self.entries.get(n)
        if hit is None:
            hit = self.entries.get(_norm(_strip_generic(text)))
        return hit

    def match_tokens(self, tokens: list[str]) -> list[tuple[int, int, dict]]:
        """
        Longest-match-wins scan over a normalized token list.

        Returns ``(start, end, entry)`` spans with ``end`` exclusive, in order of
        appearance and non-overlapping. The span is what lets the caller union
        the corresponding word boxes into pin geometry and mark those tokens as
        consumed so Tier 2 does not re-emit them.
        """
        out: list[tuple[int, int, dict]] = []
        n = len(tokens)
        i = 0
        while i < n:
            matched = False
            for span in range(min(self._max_gram, n - i), 0, -1):
                gram = tokens[i:i + span]
                key = " ".join(gram)
                if len(key) < MIN_KEY_LEN:
                    continue
                entry = self.entries.get(key)
                if entry is None:
                    continue
                if span == 1 and key in AMBIGUOUS_SINGLE_TOKENS:
                    continue
                out.append((i, i + span, entry))
                i += span
                matched = True
                break
            if not matched:
                i += 1
        return out

    # -- reporting ----------------------------------------------------------

    def stats(self) -> dict:
        by_tier: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for e in self.entries.values():
            by_tier[e["tier"]] = by_tier.get(e["tier"], 0) + 1
            by_type[e["type"]] = by_type.get(e["type"], 0) + 1
        return {
            "keys": len(self.entries),
            "canonical_names": len({e["canonical"] for e in self.entries.values()}),
            "with_coords": sum(1 for e in self.entries.values() if e.get("lat") is not None),
            "by_tier": dict(sorted(by_tier.items())),
            "by_pin_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        }


def _add(entries: dict[str, dict], key: str, entry: dict) -> None:
    """Insert a key, keeping the first (higher-tier sources are added first)."""
    if not key or len(key) < MIN_KEY_LEN:
        return
    if key in CHROME_TOKENS:
        return
    entries.setdefault(key, entry)


# Several GNIS features share a collapsed key once the generic suffix is
# stripped: "Florida Municipio", "Florida Barrio" and "Florida Zona Urbana" all
# reduce to "florida". An FR24 map label at that zoom means the municipio, so
# insertion is ordered to make the municipio win the collapsed key. Each feature
# is still reachable under its own full name ("florida barrio" stays distinct).
_NAME_RANK = (
    ("municipio", 0),
    ("zona urbana", 2),
    ("comunidad", 2),
    ("census designated place", 2),
    ("subbarrio", 3),
    ("barrio", 3),
)


def _name_rank(name: str) -> int:
    low = name.lower()
    for token, rank in _NAME_RANK:
        if token in low:
            return rank
    return 1  # bare name, no generic qualifier


def _class_rank(fclass: str) -> int:
    if fclass in CLASS_TIER_HIGH:
        return 0
    if fclass in CLASS_TIER_GEO:
        return 1
    return 2


def build_gazetteer() -> Gazetteer:
    """Assemble the match index from GNIS + landing zones + static anchors."""
    entries: dict[str, dict] = {}

    # 1) Static ICAO anchors first — exact codes, highest confidence.
    for code, name, lat, lon in STATIC_ANCHORS:
        entry = {
            "canonical": name, "type": "airport", "feature_class": "Airport",
            "lat": lat, "lon": lon, "source": "static_anchor",
            "tier": "anchor", "base_confidence": BASE_CONF_ANCHOR,
        }
        _add(entries, _norm(code), entry)
        _add(entries, _norm(name), entry)

    # 2) Landing-zone + military-aviation registries (ICAO/IATA → name).
    reg = load_registry()
    for code, name in (reg.get("names") or {}).items():
        if not name:
            continue
        entry = {
            "canonical": name, "type": "airport", "feature_class": "Airport",
            "lat": None, "lon": None, "source": "landing_zone_registry",
            "tier": "high", "base_confidence": BASE_CONF_HIGH,
        }
        _add(entries, _norm(code), entry)
        _add(entries, _norm(name), entry)

    # 3) GNIS — the bulk of the vocabulary. Sorted so that when several features
    #    collapse to the same key, the one an FR24 label most likely means wins.
    gnis_places = sorted(
        (p for p in (reg.get("gnis") or []) if (p.get("name") or "").strip()),
        key=lambda p: (_class_rank(p.get("feature_class") or ""),
                       _name_rank(p["name"]),
                       p["name"]),
    )
    for place in gnis_places:
        name = (place.get("name") or "").strip()
        fclass = place.get("feature_class") or ""
        if fclass in CLASS_TIER_HIGH:
            tier, base = "high", BASE_CONF_HIGH
        elif fclass in CLASS_TIER_GEO:
            tier, base = "geo", BASE_CONF_GEO
        else:
            tier, base = "low", BASE_CONF_LOW
        entry = {
            "canonical": name,
            "type": CLASS_TO_PIN_TYPE.get(fclass, "unknown"),
            "feature_class": fclass,
            "lat": place.get("lat"), "lon": place.get("lon"),
            "source": "gnis", "tier": tier, "base_confidence": base,
        }
        _add(entries, _norm(name), entry)
        _add(entries, _norm(_strip_generic(name)), entry)

    # 4) Off-island regional features GNIS-PR does not cover.
    for name, ptype in REGIONAL_EXTRAS:
        entry = {
            "canonical": name, "type": ptype, "feature_class": "Regional",
            "lat": None, "lon": None, "source": "regional_extra",
            "tier": "geo", "base_confidence": BASE_CONF_GEO,
        }
        _add(entries, _norm(name), entry)

    return Gazetteer(entries)


_GAZ: Gazetteer | None = None


def load_gazetteer(force: bool = False) -> Gazetteer:
    """Process-cached gazetteer. Build cost is ~0.1 s, so no on-disk cache."""
    global _GAZ
    if _GAZ is None or force:
        _GAZ = build_gazetteer()
    return _GAZ


def tokenize(words: list[str]) -> tuple[list[str], list[int]]:
    """
    Normalize OCR words into match tokens, keeping a back-pointer to the word
    each token came from.

    ``_norm`` collapses punctuation to spaces, so one OCR word can yield several
    tokens ("Bayamón/Cataño" → ["bayamon", "catano"]). Both map back to the same
    word box, which is what the extractor needs to union geometry.

    Returns ``(tokens, owner_index)`` — parallel lists.
    """
    tokens: list[str] = []
    owners: list[int] = []
    for i, w in enumerate(words):
        for tok in _norm(w or "").split():
            if tok in CHROME_TOKENS:
                continue
            tokens.append(tok)
            owners.append(i)
    return tokens, owners


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Inspect the RLSM place-name gazetteer built from GNIS.")
    ap.add_argument("--stats", action="store_true", help="Print index statistics.")
    ap.add_argument("--lookup", type=str, default="",
                    help="Resolve a single label and print its entry.")
    args = ap.parse_args()

    gaz = load_gazetteer()
    if args.lookup:
        hit = gaz.lookup(args.lookup)
        print(json.dumps({"query": args.lookup, "hit": hit}, indent=2, ensure_ascii=False))
        return
    print(json.dumps(gaz.stats(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
