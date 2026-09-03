"""
RLSM derived extractors. Parse already-stored OCR observations into structured
tables:

  - aircraft_observations  (from aircraft_card + top_bar zones)
  - labeled_pins           (from the word boxes of every label-bearing zone,
                            matched against the GNIS gazetteer in
                            fr24/rlsm_gazetteer.py; carries real pixel geometry)
  - flight_track_features  (populated by fr24/rlsm_flight_track.py — the
                            speed/heading heuristic, plus an optional CV
                            track-vectorizer pass; NOT produced by this module)
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
import contextlib
import json
import re
import sqlite3
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
        with contextlib.suppress(ValueError):
            result["altitude_ft"] = int(m.group(1).replace(",", ""))

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

# Zones whose word boxes are scanned for place labels, with a per-zone
# confidence multiplier.
#
# label_layer (5-65%) is the sparse-text map crop and the primary source.
# aircraft_card (65-95%) is already OCR'd for the aircraft extractor, so reading
# its words costs nothing — and it is the only way map labels in the bottom 35%
# of the frame are seen at all. It gets a lower weight because PSM 6 on a card
# zone is a weaker source for sparse map text than PSM 11 on the map crop.
LABEL_ZONE_WEIGHTS = {
    "label_layer":   1.00,
    "map_center":    1.00,   # legacy 6-zone runs
    "aircraft_card": 0.80,
}

# A Tier-2 candidate needs at least this many characters to be worth a row.
MIN_UNKNOWN_LEN = 4


def _normalize_label(s: str) -> str:
    """Normalize a raw label for storage."""
    return s.strip().title()


def _latest_zone_observations(conn: sqlite3.Connection, sid: int) -> list:
    """
    Newest observation per zone for one screenshot.

    Raw OCR is append-only (re-runs write fresh rows under a new run_id rather
    than overwriting), so a screenshot can carry rows from the legacy 6-zone run,
    the 3-zone run, and a --reocr-boxes pass. Taking MAX(obs_id) per zone means
    the extractor reads the newest read of each zone instead of concatenating
    every historical one.
    """
    return conn.execute(
        """SELECT zone, raw_text, raw_lines_json, confidence_mean
           FROM ocr_observations
           WHERE obs_id IN (
               SELECT MAX(obs_id) FROM ocr_observations
               WHERE screenshot_id = ? GROUP BY zone)
           ORDER BY zone""",
        (sid,),
    ).fetchall()


def _pin_confidence(entry: dict, span_len: int, word_conf: float,
                    zone_weight: float) -> float:
    """
    Confidence from four signals, replacing the old constant 0.70.

      - the gazetteer entry's tier (anchor / high / geo / low)
      - how many tokens the match consumed (multi-word hits are far less likely
        to be coincidence than single-token ones)
      - mean Tesseract confidence over the matched words
      - which zone the words came from
    """
    conf = float(entry.get("base_confidence", 0.5))
    if span_len >= 3:
        conf += 0.06
    elif span_len == 2:
        conf += 0.04
    # OCR quality: full credit at 90+, a real penalty below 50.
    conf += max(-0.15, min(0.06, (word_conf - 75.0) / 250.0))
    conf *= zone_weight
    return round(max(0.05, min(0.97, conf)), 3)


def _classify_unknown(label: str) -> tuple:
    """Weak classifier for a Tier-2 candidate with no gazetteer entry."""
    up = label.upper()
    if any(t in up for t in ("AIRPORT", "AIRFIELD", "AEROPUERTO")):
        return "airport", 0.45
    if any(t in up for t in ("BAY", "BAHIA", "LAGUNA", "LAGOON", "LAKE",
                             "RIVER", "RIO", "SEA", "OCEAN", "CANO")):
        return "water", 0.40
    if any(t in up for t in ("HWY", "HIGHWAY", "PR-", "ROUTE", "EXPRESO")):
        return "highway", 0.40
    return "unknown", 0.25


def scan_words_for_pois(words: list, zone_weight: float = 1.0) -> list:
    """
    Two-tier place extraction over a zone's OCR **word boxes**.

    Tier 1 matches gazetteer n-grams with word boundaries and records the token
    span each hit consumed. Tier 2 then emits only from runs of leftover tokens —
    which is what the old ``matched_spans`` list (computed and then never read)
    was meant to do. Under the old substring scan every Tier-1 hit was re-emitted
    as an overlapping Tier-2 "unknown": ``"FLORIDA Bayamon"`` produced three rows
    (``Bayamón``, ``Florida``, and junk ``"FLORIDA Bayamon"`` at 0.25) and the
    junk row fell under the 0.5 review threshold, so a meaningful share of the
    review backlog was self-inflicted.

    Returns a list of dicts with ``label``, ``entry`` (None for Tier 2),
    ``pin_type``, ``confidence`` and ``words`` (the source boxes).
    """
    from fr24.rlsm_gazetteer import load_gazetteer, tokenize

    if not words:
        return []
    gaz = load_gazetteer()
    texts = [w.get("t", "") for w in words]
    tokens, owners = tokenize(texts)
    if not tokens:
        return []

    out = []
    consumed = [False] * len(tokens)

    # Tier 1 — gazetteer hits.
    for start, end, entry in gaz.match_tokens(tokens):
        for i in range(start, end):
            consumed[i] = True
        src = [words[j] for j in sorted({owners[i] for i in range(start, end)})]
        wconf = sum(w.get("c", 0.0) for w in src) / max(1, len(src))
        out.append({
            "label": entry["canonical"],
            "entry": entry,
            "pin_type": entry["type"],
            "confidence": _pin_confidence(entry, end - start, wconf, zone_weight),
            "words": src,
        })

    # Tier 2 — maximal runs of tokens no Tier-1 match claimed.
    i = 0
    while i < len(tokens):
        if consumed[i]:
            i += 1
            continue
        j = i
        while j < len(tokens) and not consumed[j]:
            j += 1
        run_owners = sorted({owners[k] for k in range(i, j)})
        raw = " ".join(words[o].get("t", "") for o in run_owners).strip()
        if len(raw) >= MIN_UNKNOWN_LEN and any(ch.isalpha() for ch in raw):
            src = [words[o] for o in run_owners]
            wconf = sum(w.get("c", 0.0) for w in src) / max(1, len(src))
            ptype, base = _classify_unknown(raw)
            out.append({
                "label": raw,
                "entry": None,
                "pin_type": ptype,
                "confidence": round(max(0.05, base * zone_weight
                                        + max(-0.10, (wconf - 75.0) / 300.0)), 3),
                "words": src,
            })
        i = j

    return out


def extract_labeled_pins(conn: sqlite3.Connection, run_id: int,
                          limit: int = 0, reset: bool = False) -> dict:
    """
    Word-box place-label extractor.

    Reads the per-word geometry stored in ``ocr_observations.raw_lines_json``
    (see fr24/rlsm_wordboxes.py) rather than the flat text blob, and matches it
    against the GNIS-backed gazetteer in fr24/rlsm_gazetteer.py — 5,744 keys
    across the archipelago, against the 91 hardcoded names this used to carry.

    Every pin gets **real geometry**: ``bbox_*`` and ``centroid_*`` are the union
    box over the matched words. They used to be inserted as six literal ``None``
    values, which meant a "labeled pin" was a name with no position on the frame
    — and the per-screenshot affine geocoder needs two located pins to fit.

    Tier 1 rows carry a gazetteer entry; Tier 2 rows are leftover token runs kept
    as ``unknown`` candidates for review. Deduplicated per screenshot, highest
    confidence winning.
    """
    from fr24.rlsm_wordboxes import load_words, union_box

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
    n_no_boxes = 0
    for (sid,) in rows:
        observations = _latest_zone_observations(conn, sid)
        if not observations:
            continue

        best: dict = {}
        saw_boxes = False
        for zone, _raw_text, raw_lines_json, _conf_mean in observations:
            weight = LABEL_ZONE_WEIGHTS.get(zone)
            if weight is None:
                continue
            words = load_words(raw_lines_json)
            if not words:
                continue
            saw_boxes = True
            for hit in scan_words_for_pois(words, zone_weight=weight):
                key = hit["label"].casefold()
                if key not in best or hit["confidence"] > best[key]["confidence"]:
                    best[key] = hit

        if not saw_boxes:
            # Pre-word-box observation. Skipped rather than emitted without
            # geometry: run `--stage ocr --reocr-boxes` to backfill.
            n_no_boxes += 1
            continue

        for hit in best.values():
            box = union_box(hit["words"])
            bx, by, bw, bh = box if box else (None, None, None, None)
            cx = bx + bw // 2 if box else None
            cy = by + bh // 2 if box else None
            conn.execute(
                """INSERT INTO labeled_pins
                   (screenshot_id, run_id, raw_label, normalized_label,
                    bbox_x, bbox_y, bbox_w, bbox_h, centroid_x, centroid_y,
                    pin_type_guess, confidence, review_status, observed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sid, run_id, hit["label"], _normalize_label(hit["label"]),
                 bx, by, bw, bh, cx, cy,
                 hit["pin_type"], hit["confidence"], "unreviewed", _iso_now()),
            )
            n_emitted += 1

    conn.commit()
    return {"kind": "labeled_poi", "emitted": n_emitted, "targets": len(rows),
            "skipped_no_word_boxes": n_no_boxes}


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
            "INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed) VALUES ('labeled_poi_v3_wordbox', ?, 'in_progress', 0, 0, 0)",
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
