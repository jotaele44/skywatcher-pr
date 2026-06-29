"""
RLSM derived extractors. Parse already-stored OCR observations into structured
tables:

  - aircraft_observations  (from aircraft_card + top_bar zones)
  - labeled_pins           (from label_layer + map_center zones)
  - flight_track_features  (placeholder; deferred pending route_extractor integration)
  - manual_review_queue    (low-conf rows, conflicts)

Idempotent: re-running on already-processed screenshots replaces only the
derived rows, never touches raw ocr_observations.

CLI:
    python3 -m fr24.rlsm_extractors --kind aircraft       [--limit N]
    python3 -m fr24.rlsm_extractors --kind labeled_poi    [--limit N]
    python3 -m fr24.rlsm_extractors --kind review_queue
    python3 -m fr24.rlsm_extractors --kind all            [--limit N]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ----------------------------- aircraft extractor ---------------------------

# FAA N-numbers: N followed by 1-5 chars (digits, optional 1-2 trailing letters).
RE_REG_N      = re.compile(r"\bN[0-9]{1,5}[A-Z]{0,2}\b")
RE_REG_C      = re.compile(r"\bC-[A-Z]{4}\b")        # Canada
RE_REG_OE     = re.compile(r"\b[A-Z]{2}-[A-Z]{3}\b") # generic ICAO-style
RE_ALT        = re.compile(r"([0-9][0-9,]*)\s*ft\b", re.I)
RE_SPEED_MPH  = re.compile(r"([0-9]{1,3})\s*mph\b", re.I)
RE_SPEED_KT   = re.compile(r"([0-9]{1,3})\s*kt\b", re.I)
RE_HEADING    = re.compile(r"\bHEADING\b[^0-9]{0,8}(\d{1,3})", re.I)
RE_CALLSIGN   = re.compile(r"\b([A-Z]{2,4}[0-9]{1,4}[A-Z]?)\b")

# Operator hints (substring → canonical). Expandable.
OPERATOR_HINTS = [
    ("Coast Guard",  "USCG"),
    ("Air Force",    "USAF"),
    ("Air Cargo",    "AirCargo"),
    ("AirCargo",     "AirCargo"),
    ("CARIBBEAN",    "Caribbean"),
    ("BAYAMON",      "Municipality"),
    ("CAGUAS",       "Municipality"),
    ("ANASCO",       "Municipality"),
]

# Aircraft type patterns extracted from aircraft_card text.
RE_TYPE_BELL  = re.compile(r"\bB-?407\b|\bBell\s*407\b", re.I)
RE_TYPE_AS350 = re.compile(r"\bAS-?350\b|\bEcureuil\b", re.I)
RE_TYPE_R44   = re.compile(r"\bR-?44\b|\bRobin\b|\bRobinson\b", re.I)


def _scan_text(text: str) -> dict:
    """Apply all aircraft regexes and hints to a blob of text."""
    result: dict = {}
    m = RE_REG_N.search(text)
    if not m:
        m = RE_REG_C.search(text)
    if not m:
        m = RE_REG_OE.search(text)
    if m:
        result["registration"] = m.group(0)

    m = RE_ALT.search(text)
    if m:
        try:
            result["altitude_ft"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass

    m = RE_SPEED_KT.search(text)
    if m:
        result["speed_kt"] = int(m.group(1))
    elif (m := RE_SPEED_MPH.search(text)):
        result["speed_kt"] = int(int(m.group(1)) * 0.868976)

    m = RE_HEADING.search(text)
    if m:
        result["heading_deg"] = int(m.group(1))

    # Callsign: only if no registration found and pattern looks plausible
    if "registration" not in result:
        m = RE_CALLSIGN.search(text)
        if m:
            result["callsign"] = m.group(1)

    # Aircraft type hints
    if RE_TYPE_BELL.search(text):
        result["aircraft_type"] = "B407"
    elif RE_TYPE_AS350.search(text):
        result["aircraft_type"] = "AS350"
    elif RE_TYPE_R44.search(text):
        result["aircraft_type"] = "R44"

    # Operator hints
    for substr, canonical in OPERATOR_HINTS:
        if substr.upper() in text.upper():
            result["operator_text"] = canonical
            break

    return result


def extract_aircraft(conn: sqlite3.Connection, run_id: int, limit: int = 0) -> dict:
    """Extract aircraft observations from OCR text."""
    sql = """SELECT s.screenshot_id
             FROM screenshots s
             WHERE s.ocr_status = 'ok'
               AND NOT EXISTS (SELECT 1 FROM aircraft_observations a WHERE a.screenshot_id = s.screenshot_id)
             ORDER BY s.screenshot_id"""
    if limit:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql).fetchall()

    n_emitted = 0
    for (sid,) in rows:
        # Pull OCR text from aircraft_card + top_bar + map_center (registration can appear
        # in "Recent NXXXXX flights" map-overlay text when the user taps an aircraft history).
        text_rows = conn.execute(
            "SELECT zone, raw_text, confidence_mean FROM ocr_observations "
            "WHERE screenshot_id=? AND zone IN ('aircraft_card','top_bar','map_center')",
            (sid,),
        ).fetchall()
        if not text_rows:
            continue

        combined = " ".join(r[1] for r in text_rows if r[1])
        source_zone = "+".join(r[0] for r in text_rows if r[1])
        avg_conf = (sum(r[2] for r in text_rows if r[2] is not None)
                    / max(1, sum(1 for r in text_rows if r[2] is not None)))

        fields = _scan_text(combined)
        if not fields:
            continue

        reg   = fields.get("registration")
        call  = fields.get("callsign")
        atype = fields.get("aircraft_type")
        alt   = fields.get("altitude_ft")
        speed = fields.get("speed_kt")
        hdg   = fields.get("heading_deg")
        op    = fields.get("operator_text")

        if reg and atype:
            identity_status = "confirmed"
            confidence = min(0.95, avg_conf / 100 + 0.1)
        elif reg:
            identity_status = "partial"
            confidence = min(0.75, avg_conf / 100)
        else:
            identity_status = "unknown"
            confidence = min(0.4, avg_conf / 100)

        conn.execute(
            """INSERT INTO aircraft_observations
               (screenshot_id, run_id, registration, callsign, aircraft_type,
                altitude_ft, speed_kt, heading_deg, operator_text,
                identity_status, confidence, source_zone, raw_excerpt, observed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sid, run_id, reg, call, atype, alt, speed, hdg, op,
             identity_status, confidence, source_zone,
             combined[:200], _iso_now()),
        )
        n_emitted += 1

    conn.commit()
    return {"kind": "aircraft", "emitted": n_emitted, "targets": len(rows)}


# ----------------------------- labeled-POI extractor ------------------------

_VOWELS = set("AEIOU")

# USA / generic tokens to skip
SKIP_TOKENS = {
    "USA", "MAR", "USA", "AIRPORT", "Air Force",
    "Coast Guard", "Air Cargo", "AirCargo",
}


def _ascii_fold(s: str) -> str:
    """Very simple accent-strip for matching."""
    return (s.replace("Á", "A").replace("É", "E").replace("Í", "I")
             .replace("Ó", "O").replace("Ú", "U").replace("Ñ", "N")
             .replace("á", "a").replace("é", "e").replace("í", "i")
             .replace("ó", "o").replace("ú", "u").replace("ñ", "n"))


def _normalize_for_match(s: str) -> str:
    return _ascii_fold(s).upper().strip()


def _normalize_label(s: str) -> str:
    """Normalize a raw label for storage."""
    return s.strip().title()


def _load_pr_vocab() -> dict:
    """
    Load PR + Caribbean POI vocabulary from multiple sources. Returns a dict:
        norm_ascii_upper -> {"canonical": str, "type": str, "lat": float?, "lon": float?, "source": str}
    """
    vocab: dict = {}
    # Static anchors (5 key airports / facilities known to appear in FR24 labels)
    static = [
        ("TJSJ", "Luis Muñoz Marín International Airport", "airport",   18.4394, -66.0018),
        ("TJIG", "Fernando Luis Ribas Dominicci Airport",  "airport",   18.4567, -66.0982),
        ("TJBQ", "Rafael Hernández Airport",              "airport",   18.4949, -67.1294),
        ("TJMZ", "Eugenio María de Hostos Airport",       "airport",   18.2556, -67.1485),
        ("TJNR", "José Aponte de la Torre Airport",       "airport",   18.2453, -65.6436),
    ]
    for code, name, ptype, lat, lon in static:
        vocab[_normalize_for_match(code)] = {"canonical": name, "type": ptype, "lat": lat, "lon": lon, "source": "static_anchor"}
        vocab[_normalize_for_match(name)] = {"canonical": name, "type": ptype, "lat": lat, "lon": lon, "source": "static_anchor"}

    # Common PR municipality names
    municipalities = [
        "ADJUNTAS", "AGUADA", "AGUADILLA", "AGUAS BUENAS", "AIBONITO",
        "AÑASCO", "ARECIBO", "ARROYO", "BARCELONETA", "BARRANQUITAS",
        "BAYAMÓN", "CABO ROJO", "CAGUAS", "CAMUY", "CANÓVANAS",
        "CAROLINA", "CATAÑO", "CAYEY", "CEIBA", "CIALES",
        "CIDRA", "COAMO", "COMERÍO", "COROZAL", "CULEBRA",
        "DORADO", "FAJARDO", "FLORIDA", "GUÁNICA", "GUAYAMA",
        "GUAYANILLA", "GUAYNABO", "GURABO", "HATILLO", "HORMIGUEROS",
        "HUMACAO", "ISABELA", "JAYUYA", "JUANA DÍAZ", "JUNCOS",
        "LAJAS", "LARES", "LAS MARÍAS", "LAS PIEDRAS", "LOÍZA",
        "LUQUILLO", "MANATÍ", "MARICAO", "MAUNABO", "MAYAGÜEZ",
        "MOCA", "MOROVIS", "NAGUABO", "NARANJITO", "OROCOVIS",
        "PATILLAS", "PEÑUELAS", "PONCE", "QUEBRADILLAS", "RINCÓN",
        "RÍO GRANDE", "SABANA GRANDE", "SALINAS", "SAN GERMÁN", "SAN JUAN",
        "SAN LORENZO", "SAN SEBASTIÁN", "SANTA ISABEL", "TOA ALTA", "TOA BAJA",
        "TRUJILLO ALTO", "UTUADO", "VEGA ALTA", "VEGA BAJA", "VIEQUES",
        "VILLALBA", "YABUCOA", "YAUCO",
    ]
    for name in municipalities:
        key = _normalize_for_match(name)
        vocab[key] = {"canonical": _normalize_label(name), "type": "municipality",
                      "lat": None, "lon": None, "source": "pr_municipalities"}

    # Caribbean / water features
    for name, ptype in [
        ("CARIBBEAN SEA",  "water"), ("ATLANTIC OCEAN", "water"),
        ("MONA PASSAGE",   "water"), ("VIEQUES SOUND",  "water"),
        ("DOMINICAN REPUBLIC", "territory"), ("US VIRGIN ISLANDS", "territory"),
        ("SAINT THOMAS",   "territory"), ("SAINT CROIX",   "territory"),
        ("CULEBRA",        "territory"),
    ]:
        vocab[_normalize_for_match(name)] = {"canonical": name.title(), "type": ptype,
                                              "lat": None, "lon": None, "source": "caribbean"}
    return vocab


_PR_VOCAB: dict = {}


def _scan_text_for_pois(text: str) -> list:
    """
    Two-tier extraction from a single OCR text blob:
      1. Substring match against the PR vocabulary (high-confidence Tier-1 hits)
      2. Capitalized word groups that don't match (low-confidence Tier-2 candidates)
    Returns: list of (matched_string, vocab_entry_or_None_for_unknown)
    """
    global _PR_VOCAB
    if not _PR_VOCAB:
        _PR_VOCAB = _load_pr_vocab()

    results = []
    text_upper = _normalize_for_match(text)

    # Tier 1 – vocabulary hits
    matched_spans = []
    for key, entry in _PR_VOCAB.items():
        if key in text_upper:
            results.append((entry["canonical"], entry))
            # track rough span to avoid double-emitting sub-matches
            idx = text_upper.find(key)
            matched_spans.append((idx, idx + len(key)))

    # Tier 2 – capitalized word groups not already matched
    for m in re.finditer(r'\b([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+)*)\b', text):
        word = m.group(1)
        norm = _normalize_for_match(word)
        if norm in _PR_VOCAB:
            continue
        if len(word) < 4 or word.upper() in SKIP_TOKENS:
            continue
        # Skip purely numeric or single-letter tokens
        if not any(c.isalpha() for c in word):
            continue
        results.append((word, None))

    return results


def _classify_poi(label: str, vocab_entry) -> tuple:
    """Fallback classifier for tokens with no vocab entry."""
    if vocab_entry:
        return vocab_entry["type"], min(0.90, 0.70)
    label_up = label.upper()
    if any(t in label_up for t in ("AIRPORT", "AIRFIELD", "AEROPUERTO")):
        return "airport", 0.55
    if any(t in label_up for t in ("BAY", "LAGOON", "LAKE", "RIVER", "SEA", "OCEAN")):
        return "water", 0.45
    if any(t in label_up for t in ("HWY", "HIGHWAY", "PR-", "ROUTE")):
        return "highway", 0.45
    return "unknown", 0.25


def extract_labeled_pins(conn: sqlite3.Connection, run_id: int,
                          limit: int = 0, reset: bool = False) -> dict:
    """
    v2 extractor: tokenize OCR text and substring-match against PR vocabulary
    (5 anchors + 279 municipalities + Caribbean territories + water features).

    Two-tier emission:
      Tier 1 (matched): raw_label = canonical name, pin_type_guess in
              {airport, anchor, municipality, territory, water}, confidence
              boosted to 90 if OCR mean was high enough.
      Tier 2 (unknown_label_candidate): unmatched but plausibly-labeled tokens
              from the OCR text. Marked review_status='unreviewed'.
    """
    if reset:
        conn.execute("DELETE FROM labeled_pins")
        conn.commit()

    sql = """SELECT s.screenshot_id
             FROM screenshots s
             WHERE s.ocr_status = 'ok'
               AND NOT EXISTS (SELECT 1 FROM labeled_pins p WHERE p.screenshot_id = s.screenshot_id)
             ORDER BY s.screenshot_id"""
    if limit:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql).fetchall()

    n_emitted = 0
    for (sid,) in rows:
        # Only use ONE of label_layer/map_center per screenshot to avoid double-emit.
        # label_layer takes priority because its OCR config targets sparse text.
        text_rows = conn.execute(
            "SELECT raw_text, confidence_mean FROM ocr_observations "
            "WHERE screenshot_id=? AND zone = 'label_layer'",
            (sid,),
        ).fetchall()
        if not text_rows:
            text_rows = conn.execute(
                "SELECT raw_text, confidence_mean FROM ocr_observations "
                "WHERE screenshot_id=? AND zone = 'map_center'",
                (sid,),
            ).fetchall()
        if not text_rows:
            continue

        combined = " ".join(r[0] for r in text_rows if r[0])
        avg_conf = (sum(r[1] for r in text_rows if r[1] is not None)
                    / max(1, sum(1 for r in text_rows if r[1] is not None)))

        hits = _scan_text_for_pois(combined)
        seen_labels: set = set()
        for raw_label, vocab_entry in hits:
            norm = _normalize_for_match(raw_label)
            if norm in seen_labels:
                continue
            seen_labels.add(norm)

            poi_type, confidence = _classify_poi(raw_label, vocab_entry)
            # Boost confidence if OCR was high quality
            if avg_conf > 70 and vocab_entry:
                confidence = min(0.95, confidence + 0.15)

            conn.execute(
                """INSERT INTO labeled_pins
                   (screenshot_id, run_id, raw_label, normalized_label,
                    bbox_x, bbox_y, bbox_w, bbox_h, centroid_x, centroid_y,
                    pin_type_guess, confidence, review_status, observed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sid, run_id, raw_label, _normalize_label(raw_label),
                 None, None, None, None, None, None,
                 poi_type, confidence, "unreviewed", _iso_now()),
            )
            n_emitted += 1

    conn.commit()
    return {"kind": "labeled_poi", "emitted": n_emitted, "targets": len(rows)}


# ----------------------------- aircraft roster (export helper) ---------------

def build_aircraft_roster(conn: sqlite3.Connection) -> dict:
    """
    Aggregate aircraft_observations into a per-aircraft roster CSV (no new table —
    materialized as outputs/aircraft_roster.csv via the exporter).
    Returns counts.
    """
    rows = conn.execute(
        "SELECT DISTINCT registration FROM aircraft_observations "
        "WHERE registration IS NOT NULL ORDER BY registration"
    ).fetchall()
    return {"distinct_registrations": len(rows)}


# ----------------------------- geo-anchor seeding ---------------------------

def seed_geo_anchors(conn: sqlite3.Connection) -> dict:
    """Seed static geo anchors from georef_anchors.csv if it exists."""
    anchors_csv = REPO / "data" / "rlsm" / "georef_anchors.csv"
    conn.execute("DELETE FROM geo_anchors WHERE source='georef_anchors.csv' AND anchor_kind='static'")
    conn.commit()

    if not anchors_csv.exists():
        # 6) Geo anchor failures — placeholder until we wire georef_anchors.csv
        return {"seeded": 0, "reason": "georef_anchors.csv not found"}

    import csv
    n = 0
    with open(anchors_csv, newline="") as f:
        for row in csv.DictReader(f):
            try:
                conn.execute(
                    """INSERT INTO geo_anchors
                       (screenshot_id, anchor_kind, name, lat, lon, confidence, source, notes, observed_at)
                       VALUES (NULL, 'static', ?, ?, ?, 1.0, 'georef_anchors.csv', ?, ?)""",
                    (row.get("name", ""), float(row["lat"]), float(row["lon"]),
                     row.get("notes", ""), _iso_now()),
                )
                n += 1
            except (KeyError, ValueError):
                continue
    conn.commit()
    return {"seeded": n}


# ----------------------------- review queue ---------------------------------

LOW_CONF_POI_THRESHOLD  = 0.5
LOW_CONF_OCR_THRESHOLD  = 50.0   # confidence_mean %


def build_review_queues(conn: sqlite3.Connection) -> dict:
    """
    Re-derive the manual review queue from current observations.
    Wipes only the auto-derived rows so reviewer-marked rows stay.
    """
    conn.execute("DELETE FROM manual_review_queue WHERE review_status='unreviewed'")
    conn.commit()

    ts = _iso_now()
    n_total = 0

    # 1) Aircraft identity conflicts
    conn.execute("""
        INSERT INTO manual_review_queue (screenshot_id, item_kind, item_ref_table, item_ref_id, reason, severity, review_status, created_at)
        SELECT screenshot_id, 'aircraft_identity_conflict', 'aircraft_observations', aircraft_obs_id,
               'identity_status=' || identity_status || ' reg=' || COALESCE(registration,'?') || ' type=' || COALESCE(aircraft_type,'?'),
               CASE identity_status WHEN 'conflicting' THEN 'high' WHEN 'partial' THEN 'medium' ELSE 'low' END,
      'unreviewed', ?
        FROM aircraft_observations
        WHERE identity_status IN ('partial', 'conflicting', 'unknown')
    """, (ts,))
    n_total += conn.execute("SELECT changes()").fetchone()[0]

    # 2) Labeled POI low confidence
    conn.execute("""
        INSERT INTO manual_review_queue (screenshot_id, item_kind, item_ref_table, item_ref_id, reason, severity, review_status, created_at)
        SELECT screenshot_id, 'labeled_pin_low_conf', 'labeled_pins', pin_id,
               'label="' || raw_label || '" type_guess=' || pin_type_guess || ' conf=' || ROUND(COALESCE(confidence,0),1),
               'low', 'unreviewed', ?
        FROM labeled_pins WHERE confidence IS NOT NULL AND confidence < ?
        """, (ts, LOW_CONF_POI_THRESHOLD))
    n_total += conn.execute("SELECT changes()").fetchone()[0]

    # 3) OCR low confidence
    conn.execute("""
        INSERT INTO manual_review_queue (screenshot_id, item_kind, item_ref_table, item_ref_id, reason, severity, review_status, created_at)
        SELECT screenshot_id, 'ocr_low_conf', 'ocr_observations', obs_id,
               'mean confidence below threshold: ' || ROUND(confidence_mean,1) || ' (zone=' || zone || ')',
               CASE WHEN confidence_mean < 30 THEN 'high' WHEN confidence_mean < 40 THEN 'medium' ELSE 'low' END,
               'unreviewed', ?
        FROM ocr_observations WHERE confidence_mean IS NOT NULL AND confidence_mean < ?
          AND ocr_status = 'ok'
    """, (ts, LOW_CONF_OCR_THRESHOLD))
    n_total += conn.execute("SELECT changes()").fetchone()[0]

    # 4) Unlabeled candidates (all go to review)
    conn.execute("""
        INSERT INTO manual_review_queue (screenshot_id, item_kind, item_ref_table, item_ref_id, reason, severity, review_status, created_at)
        SELECT screenshot_id, 'unlabeled_candidate', 'unlabeled_pin_candidates', candidate_id,
               'type=' || candidate_type || ' conf=' || ROUND(COALESCE(confidence,0),1),
               CASE WHEN confidence > 0.7 THEN 'high' WHEN confidence > 0.4 THEN 'medium' ELSE 'low' END,
               'unreviewed', ?
        FROM unlabeled_pin_candidates
    """, (ts,))
    n_total += conn.execute("SELECT changes()").fetchone()[0]

    # 5) Time conflicts — filename_ts vs ocr_observed status_bar time
    # Placeholder: extracting "HH:MM" from status_bar OCR and comparing to filename_ts
    time_rows = conn.execute("""
        SELECT s.screenshot_id, o.obs_id, s.filename_ts, o.raw_text
        FROM screenshots s JOIN ocr_observations o ON o.screenshot_id = s.screenshot_id
        WHERE o.zone = 'status_bar' AND s.filename_ts IS NOT NULL
          AND o.raw_text IS NOT NULL AND o.raw_text != ''
    """).fetchall()
    for sid, obs_id, fn_ts, raw in time_rows:
        m = re.search(r'\b(\d{1,2}:\d{2})\b', raw)
        if not m:
            continue
        ocr_time = m.group(1)
        # Parse filename_ts: YYYY-MM-DDTHH:MM:SS → HH:MM in 24h
        fn_match = re.search(r'T(\d{2}):(\d{2})', fn_ts or "")
        if not fn_match:
            continue
        fn_hm = f"{fn_match.group(1)}:{fn_match.group(2)}"
        if ocr_time != fn_hm:
            diff_msg = f"{ocr_time} vs filename={fn_hm}"
            sev = "high" if abs(int(fn_hm.split(":")[0]) - int(ocr_time.split(":")[0])) > 1 else "medium"
            conn.execute(
                "INSERT INTO manual_review_queue (screenshot_id, item_kind, item_ref_table, item_ref_id, reason, severity, review_status, created_at) VALUES (?, 'time_conflict', 'ocr_observations', ?, ?, ?, 'unreviewed', ?)",
                (sid, obs_id, f" (diff {diff_msg} min)", sev, ts),
            )
            n_total += 1

    conn.commit()
    return {"kind": "review_queue", "inserted": n_total}


# ----------------------------- main ----------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="RLSM derived extractors — run OCR → structured table extraction."
    )
    ap.add_argument("--kind", choices=["aircraft", "labeled_poi", "review_queue", "all"],
                    default="all")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reset-labeled-pins", action="store_true",
                    help="Clear labeled_pins before re-running (for schema changes).")
    args = ap.parse_args()

    conn = sqlite3.connect(DB, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")  # wait up to 30s for the write lock (concurrency-safe)
    # Ensure the aircraft-dedup unique index exists (idempotent migration for
    # pre-existing DBs that predate B-dedup-unique).
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_air_dedup "
        "ON aircraft_observations(screenshot_id, registration, source_zone) "
        "WHERE registration IS NOT NULL AND TRIM(registration) != ''"
    )
    out = {}
    if args.kind in ("aircraft", "all"):
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed) VALUES ('aircraft_extract', ?, 'in_progress', 0, 0, 0)",
            (_iso_now(),),
        )
        run_id = cur.lastrowid
        conn.commit()
        result = extract_aircraft(conn, run_id, args.limit)
        conn.execute(
            "UPDATE processing_runs SET ended_at=?, status='completed', n_processed=? WHERE run_id=?",
            (_iso_now(), result["emitted"], run_id),
        )
        conn.commit()
        out["aircraft"] = result

    if args.kind in ("labeled_poi", "all"):
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed) VALUES ('labeled_poi_v2', ?, 'in_progress', 0, 0, 0)",
            (_iso_now(),),
        )
        run_id = cur.lastrowid
        conn.commit()
        result = extract_labeled_pins(conn, run_id, args.limit,
                                      reset=args.reset_labeled_pins)
        conn.execute(
            "UPDATE processing_runs SET ended_at=?, status='completed', n_processed=? WHERE run_id=?",
            (_iso_now(), result["emitted"], run_id),
        )
        conn.commit()
        out["labeled_poi"] = result

    if args.kind in ("review_queue", "all"):
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed) VALUES ('review_queue', ?, 'in_progress', 0, 0, 0)",
            (_iso_now(),),
        )
        run_id = cur.lastrowid
        conn.commit()
        result = build_review_queues(conn)
        conn.execute(
            "UPDATE processing_runs SET ended_at=?, status='completed', n_processed=? WHERE run_id=?",
            (_iso_now(), result.get("inserted", 0), run_id),
        )
        conn.commit()
        out["review_queue"] = result

    conn.close()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
