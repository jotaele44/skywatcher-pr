#!/usr/bin/env python3
"""
Parse the operator's Flight Log 2025 workbook into an FR24-ingest-compatible CSV.

The workbook has several layouts across monthly sheets (May–September share one
schema, with June/August carrying two side-by-side tables; October/November use
a wider schema). This normalizes all of them into the column set consumed by
server/ingestion/ingest_data.py::ingest_fr24_csv, extracting the aircraft
registration from messy "Tail / Callsign" strings (nicknames, em-dashes, USCG
C-numbers) and dropping aircraft-type tokens that look like tails.

Usage:
    python3 scripts/parse_flight_log.py --xlsx "Flight_Log_2025.xlsx" \
        --output outputs/flight_log_2025_events.csv
"""
from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path

import openpyxl

# Type designators that the tail regex would otherwise mis-capture as a tail.
TYPE_TOKENS = {
    "R44", "R66", "H125", "H130", "AS50", "AS350", "B407", "B429", "B206",
    "MH60", "EC35", "AW139", "S76",
}
TAIL_RE = re.compile(r"\b([A-Z]\d[0-9A-Z]{1,5})\b")
# Coarse AM/Midday/PM → representative local times for the November sheet.
TIME_WORDS = {"am": "09:00:00", "midday": "12:00:00", "noon": "12:00:00", "pm": "15:00:00"}


def extract_tail(raw) -> tuple[str, str]:
    """Return (registration, status). Registration is "" unless cleanly parsed."""
    if raw is None:
        return "", "empty"
    s = str(raw).strip()
    head = s.split("(")[0].strip()  # ignore parenthetical nicknames/types
    if not head or head[0] in "—-–":
        return "", "untracked"
    if head.lower().startswith("unknown"):
        return "", "unknown"
    m = TAIL_RE.search(head.upper())
    if m and m.group(1) not in TYPE_TOKENS:
        return m.group(1), "ok"
    return "", "untracked"


def _first_last_poi(route) -> tuple[str, str]:
    if not route:
        return "", ""
    parts = re.split(r"→|->|↔|→", str(route))
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return "", ""
    return parts[0], parts[-1]


def _leading_int(value) -> str:
    m = re.search(r"\d[\d\s]*", str(value or "").replace(" ", " ").replace("\xa0", " "))
    return m.group(0).replace(" ", "") if m else ""


def _norm_date(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    s = str(value or "").strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    # "Oct 1" style (October sheet) — assume 2025.
    try:
        return datetime.strptime(f"{s} 2025", "%b %d %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _norm_time(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%H:%M:%S")
    s = str(value or "").strip().lower()
    if s in TIME_WORDS:
        return TIME_WORDS[s]
    s = s.replace(" ", "")
    m = re.match(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}:{m.group(3) or '00'}"
    return ""


def _headers(rows):
    """Return (header_row_index, {logical_name: col_index}) for one sheet."""
    for ri, r in enumerate(rows[:3]):
        labels = {str(v).strip().lower(): i for i, v in enumerate(r) if isinstance(v, str)}
        tail_cols = [i for k, i in labels.items() if "tail" in k]
        if tail_cols:
            return ri, labels, tail_cols
    return 0, {}, [4]


def _col(labels, *names, default=None):
    for n in names:
        for k, i in labels.items():
            if n in k:
                return i
    return default


def parse(xlsx_path: Path) -> list[dict]:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    out: list[dict] = []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        hr, labels, tail_cols = _headers(rows)
        date_c = _col(labels, "date", default=2)
        time_c = _col(labels, "time", default=3)
        op_c = _col(labels, "operator")
        route_c = _col(labels, "route", "poi")
        alt_c = _col(labels, "alt")
        spd_c = _col(labels, "speed")
        notes_c = _col(labels, "behavior", "mission", "note")
        conf_c = _col(labels, "conf")

        for ridx, r in enumerate(rows[hr + 1:], start=hr + 1):
            if not any(v not in (None, "") for v in r):
                continue
            for tc in tail_cols:
                if tc >= len(r):
                    continue
                # For the second table block, shift companion columns by the block offset.
                off = tc - tail_cols[0]
                reg, status = extract_tail(r[tc])
                cell = lambda c: r[c + off] if c is not None and c + off < len(r) else None
                date = _norm_date(cell(date_c))
                time = _norm_time(cell(time_c))
                if not date and status == "empty":
                    continue
                at = f"{date}T{time or '00:00:00'}" if date else ""
                origin, dest = _first_last_poi(cell(route_c))
                operator = re.split(r"/", str(cell(op_c) or ""))[0].strip() if op_c is not None else ""
                out.append({
                    "id": f"fl2025-{ws.title.lower()}-{ridx}-{tc}",
                    "at": at,
                    "callsign": reg,
                    "registration": reg,
                    "operator": operator,
                    "origin_code": origin,
                    "destination_code": dest,
                    "altitude_ft": _leading_int(cell(alt_c)) if alt_c is not None else "",
                    "ground_speed_mph": _leading_int(cell(spd_c)) if spd_c is not None else "",
                    "flight_status": str(cell(notes_c) or "").strip() if notes_c is not None else "",
                    "image_path": "",
                    "label": reg or "Unknown (untracked)",
                    "source_sheet": ws.title,
                    "confidence": str(cell(conf_c) or "").strip() if conf_c is not None else "",
                })
    return out


CSV_FIELDS = ["id", "at", "callsign", "registration", "operator", "origin_code",
              "destination_code", "altitude_ft", "ground_speed_mph", "flight_status",
              "image_path", "label", "source_sheet", "confidence"]


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse Flight Log 2025 → FR24 ingest CSV")
    ap.add_argument("--xlsx", required=True, help="Path to Flight_Log_2025.xlsx")
    ap.add_argument("--output", default="outputs/flight_log_2025_events.csv")
    args = ap.parse_args()

    rows = parse(Path(args.xlsx))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)

    tracked = [r for r in rows if r["registration"]]
    print(f"Parsed {len(rows)} rows ({len(tracked)} with a registration) → {out}")


if __name__ == "__main__":
    main()
