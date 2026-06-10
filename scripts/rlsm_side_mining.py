#!/usr/bin/env python3
"""
Phase F: OCR side-mining.

Extracts richer fields we left on the table during initial extraction:

  - origin_iata / destination_iata     (3-letter IATA codes from FR24 route line)
  - departed_text / arriving_text      ("Departed 00:14 ago", "Arriving in 04:18")
  - departed_minutes_ago / arriving_in_minutes (parsed numeric)
  - heading_deg                        ("HEADING 234°")
  - timeline_hours_visible             (hour markers from the scrubber bar)
  - aircraft_serial                    if visible in detail card

These are added as new columns on aircraft_observations (idempotent ALTER TABLE).

Run via:
    python3 scripts/rlsm_side_mining.py
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# Patterns observed in FR24 aircraft_card OCR:
ROUTE_IATA_PAT = re.compile(r"\b([A-Z]{3})\s+([A-Z]{3})\b")
# 3-letter origin and destination side-by-side, e.g. "SIG ARE", "MIA SJU", "BQN MAZ"
# Caveat: this also matches OCR garble like "SEE ALL"; we'll filter via known IATA set.

DEPARTED_PAT = re.compile(r"Departed\s+(\d{2}):(\d{2})\s+ago", re.IGNORECASE)
ARRIVING_PAT = re.compile(r"Arriving in\s+(\d{2}):(\d{2})", re.IGNORECASE)
HEADING_PAT  = re.compile(r"\bHEADING\b[^\d]{0,8}(\d{1,3})", re.IGNORECASE)
SERIAL_PAT   = re.compile(r"\bSERIAL\b[^\w]{0,5}([A-Z0-9\-]{4,15})", re.IGNORECASE)

# Hour markers in the scrubber: "7:50 AM 8:00 AM 8:10 AM"
HOUR_MARKER_PAT = re.compile(r"\b(\d{1,2}:\d{2})\s*([AP]M)\b", re.IGNORECASE)

# Known IATA codes for PR + Caribbean (filter against false positives)
KNOWN_IATA = {
    # PR major airports
    "SJU",  # Luis Munoz Marin (San Juan)
    "BQN",  # Rafael Hernandez (Aguadilla)
    "PSE",  # Mercedita (Ponce)
    "SIG",  # Fernando Luis Ribas Dominicci (Isla Grande, San Juan)
    "ARE",  # Antonio (Nery) Juarbe Pol (Arecibo)
    "MAZ",  # Eugenio Maria de Hostos (Mayaguez)
    "FAJ",  # Diego Jimenez Torres (Fajardo)
    "HUC",  # Humacao
    "VQS",  # Antonio Rivera Rodriguez (Vieques)
    "CPX",  # Benjamin Rivera Noriega (Culebra)
    "NRR",  # Jose Aponte de la Torre / former Roosevelt Roads (Ceiba)
    # Mainland US common in PR FR24 corpus
    "MIA",  # Miami
    "FLL",  # Fort Lauderdale
    "MCO",  # Orlando
    "JFK",  # John F Kennedy NYC
    "EWR",  # Newark
    "ATL",  # Atlanta
    "BOS",  # Boston
    "PHL",  # Philadelphia
    "BWI",  # Baltimore
    "DCA",  # Reagan National
    "IAD",  # Dulles
    "CLT",  # Charlotte
    "DFW",  # Dallas Fort Worth
    "PBI",  # West Palm Beach
    "TPA",  # Tampa
    "RSW",  # Fort Myers
    # USVI / BVI
    "STT",  # St. Thomas
    "STX",  # St. Croix
    "EIS",  # Tortola
    "VIJ",  # Virgin Gorda
    # Caribbean common origins
    "SDQ",  # Santo Domingo
    "STI",  # Santiago de los Caballeros
    "POP",  # Puerto Plata
    "SXM",  # St. Maarten
    "AUA",  # Aruba
    "CUR",  # Curacao
    "BGI",  # Barbados
    "MBJ",  # Montego Bay
    "KIN",  # Kingston
    "HAV",  # Havana
    "SBH",  # St. Barts
    "ANU",  # Antigua
    "PTP",  # Pointe-a-Pitre
    "FDF",  # Fort-de-France
    "DOM",  # Dominica
}


def _ensure_columns(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(aircraft_observations)")}
    new_cols = [
        ("origin_iata",           "TEXT"),
        ("destination_iata",      "TEXT"),
        ("departed_text",         "TEXT"),
        ("departed_minutes_ago",  "INTEGER"),
        ("arriving_text",         "TEXT"),
        ("arriving_in_minutes",   "INTEGER"),
        ("heading_deg_sidemined", "INTEGER"),
        ("aircraft_serial",       "TEXT"),
        ("timeline_hours_visible","TEXT"),
        ("side_mined_at",         "TEXT"),
    ]
    for name, typ in new_cols:
        if name not in cols:
            conn.execute(f"ALTER TABLE aircraft_observations ADD COLUMN {name} {typ}")
    conn.commit()


def extract_route_iata(text: str):
    """Find first OCR 'XXX YYY' pair where both are in KNOWN_IATA."""
    if not text:
        return None, None
    for m in ROUTE_IATA_PAT.finditer(text):
        a, b = m.group(1), m.group(2)
        if a in KNOWN_IATA and b in KNOWN_IATA and a != b:
            return a, b
    return None, None


def extract_timeline_hours(text: str):
    """Pull HH:MM AM/PM markers from the scrubber bar; return comma-joined."""
    if not text:
        return None
    matches = HOUR_MARKER_PAT.findall(text)
    if not matches:
        return None
    # Dedup, keep order
    seen = []
    for h, ap in matches:
        s = f"{h} {ap.upper()}"
        if s not in seen:
            seen.append(s)
    if len(seen) < 2:
        return None  # need at least 2 marks to consider a timeline
    return ", ".join(seen[:12])


def parse_hhmm_to_minutes(hh: str, mm: str) -> int:
    return int(hh) * 60 + int(mm)


def mine(dry_run: bool = False) -> dict:
    conn = sqlite3.connect(DB)
    if not dry_run:
        _ensure_columns(conn)

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed) "
        "VALUES ('side_mining', ?, 'in_progress', 0, 0, 0)",
        (_iso_now(),),
    )
    run_id = cur.lastrowid

    # Pull every aircraft_observation joined to its aircraft_card OCR text
    rows = conn.execute("""
        SELECT a.aircraft_obs_id, a.screenshot_id,
               GROUP_CONCAT(o.raw_text, ' | ') AS card_text
        FROM aircraft_observations a
        JOIN ocr_observations o ON o.screenshot_id = a.screenshot_id AND o.zone = 'aircraft_card'
        GROUP BY a.aircraft_obs_id
    """).fetchall()

    n_total = len(rows)
    n_with_route = n_with_dep = n_with_arr = n_with_head = n_with_timeline = n_with_serial = 0
    iata_counter = Counter()

    for obs_id, sid, text in rows:
        text = text or ""
        origin, dest = extract_route_iata(text)
        if origin:
            iata_counter[origin] += 1
            iata_counter[dest] += 1
            n_with_route += 1
        m_dep = DEPARTED_PAT.search(text)
        if m_dep:
            dep_text = m_dep.group(0)
            dep_min = parse_hhmm_to_minutes(m_dep.group(1), m_dep.group(2))
            n_with_dep += 1
        else:
            dep_text, dep_min = None, None
        m_arr = ARRIVING_PAT.search(text)
        if m_arr:
            arr_text = m_arr.group(0)
            arr_min = parse_hhmm_to_minutes(m_arr.group(1), m_arr.group(2))
            n_with_arr += 1
        else:
            arr_text, arr_min = None, None
        m_head = HEADING_PAT.search(text)
        heading = int(m_head.group(1)) if m_head and 0 <= int(m_head.group(1)) <= 360 else None
        if heading is not None:
            n_with_head += 1
        m_ser = SERIAL_PAT.search(text)
        serial = m_ser.group(1) if m_ser else None
        if serial:
            n_with_serial += 1
        timeline = extract_timeline_hours(text)
        if timeline:
            n_with_timeline += 1
        if not dry_run:
            conn.execute(
                """UPDATE aircraft_observations
                   SET origin_iata=?, destination_iata=?,
                       departed_text=?, departed_minutes_ago=?,
                       arriving_text=?, arriving_in_minutes=?,
                       heading_deg_sidemined=?, aircraft_serial=?,
                       timeline_hours_visible=?, side_mined_at=?
                   WHERE aircraft_obs_id=?""",
                (origin, dest, dep_text, dep_min, arr_text, arr_min,
                 heading, serial, timeline, _iso_now(), obs_id),
            )
    if not dry_run:
        conn.commit()

    cur.execute(
        "UPDATE processing_runs SET ended_at=?, status='completed', n_inputs=?, n_processed=?, notes=? WHERE run_id=?",
        (_iso_now(), n_total, n_total,
         json.dumps({"with_route": n_with_route, "with_departed": n_with_dep,
                     "with_arriving": n_with_arr, "with_heading": n_with_head,
                     "with_serial": n_with_serial, "with_timeline": n_with_timeline,
                     "top_iata": iata_counter.most_common(15)}), run_id),
    )
    conn.commit()
    conn.close()

    return {
        "rows_processed": n_total,
        "with_route_iata": n_with_route,
        "with_departed": n_with_dep,
        "with_arriving": n_with_arr,
        "with_heading": n_with_head,
        "with_serial": n_with_serial,
        "with_timeline_visible": n_with_timeline,
        "top_iata": iata_counter.most_common(15),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    out = mine(dry_run=args.dry_run)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
