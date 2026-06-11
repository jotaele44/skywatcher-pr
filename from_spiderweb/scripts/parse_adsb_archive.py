#!/usr/bin/env python3
"""
Parse a per-tail ADS-B export archive into priis.db (events + track_points).

The operator's archive holds one CSV per flight, named by FlightRadar24 flight
id (e.g. ``3aadc81d.csv``), with columns::

    Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction

where ``Position`` is a quoted ``"lat,lon"`` pair. Some tails are bundled in
nested zips, and one wrapper zip (``N79035.zip``) re-bundles the same N79036
flight ids — so flights are deduplicated by file id to avoid double-ingest.

Each flight becomes:
  * one row in ``events`` (kind='flight'), via ingest_data.ingest_fr24_csv —
    so it joins the same logs/alerts path as FR24 and Flight Log 2025 data; and
  * one row per position report in ``track_points`` (route playback), via
    ingest_data.ingest_track_points.

Usage (from repo root):
    python3 scripts/parse_adsb_archive.py \
        --zip "Archive.zip" --db server/priis.db \
        --events-csv outputs/adsb_archive_events.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
import zipfile
from pathlib import Path
from typing import Iterator

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from server.ingestion.ingest_data import (  # noqa: E402
    _connect,
    ingest_fr24_csv,
    ingest_track_points,
)
from server.ingestion.migrations import run_all as run_migrations  # noqa: E402
from server.ingestion.registration_alerts import (  # noqa: E402
    generate_alerts,
    load_watchlist,
)

DB_DEFAULT = _ROOT / "server" / "priis.db"
EVENTS_CSV_DEFAULT = _ROOT / "outputs" / "adsb_archive_events.csv"
WATCHLIST_DEFAULT = _ROOT / "configs" / "registration_watchlist.yaml"

# Tail → (aircraft_type, operator) for tails with an accompanying FAA info PDF.
KNOWN_AIRCRAFT = {
    "N413LP": ("Eurocopter AS350 B3", "CAMAPE SE"),
    "N888EV": ("MD/Hughes 369E", "Netwave Equipment Worldwide Inc"),
}

EVENT_CSV_FIELDS = [
    "id", "at", "callsign", "registration", "aircraft_type", "operator",
    "origin_code", "destination_code", "altitude_ft", "ground_speed_mph",
    "flight_status", "image_path", "label",
]


def _is_flight_csv(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]
    return (
        name.lower().endswith(".csv")
        and "__MACOSX" not in name
        and not base.startswith("._")
    )


def iter_flight_csvs(source: Path) -> Iterator[tuple[str, str]]:
    """Yield (file_id, csv_text) for every flight CSV, deduplicated by file id.

    Walks a zip (recursing into nested zips) or a directory tree. The file id is
    the CSV basename without extension (the FR24 flight id). The first
    occurrence of each id wins, so the N79035 wrapper's duplicate N79036 flights
    are ingested only once.
    """
    seen: set[str] = set()

    def _emit(name: str, data: bytes) -> Iterator[tuple[str, str]]:
        file_id = name.rsplit("/", 1)[-1][:-4]  # strip ".csv"
        if file_id in seen:
            return
        seen.add(file_id)
        yield file_id, data.decode("utf-8-sig", errors="replace")

    def _walk_zip(zf: zipfile.ZipFile) -> Iterator[tuple[str, str]]:
        # Process plain CSVs first so they win dedup over nested-zip copies.
        names = zf.namelist()
        for name in names:
            if _is_flight_csv(name):
                yield from _emit(name, zf.read(name))
        for name in names:
            if name.lower().endswith(".zip") and "__MACOSX" not in name:
                base = name.rsplit("/", 1)[-1]
                if base.startswith("._"):
                    continue
                with zipfile.ZipFile(io.BytesIO(zf.read(name))) as nested:
                    yield from _walk_zip(nested)

    if source.is_dir():
        for path in sorted(source.rglob("*")):
            if path.is_file() and _is_flight_csv(path.name):
                yield from _emit(path.name, path.read_bytes())
            elif path.is_file() and path.suffix.lower() == ".zip":
                with zipfile.ZipFile(path) as zf:
                    yield from _walk_zip(zf)
    else:
        with zipfile.ZipFile(source) as zf:
            yield from _walk_zip(zf)


def _split_position(raw: str) -> tuple[float | None, float | None]:
    parts = (raw or "").split(",")
    if len(parts) != 2:
        return None, None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None, None


def parse_flight(file_id: str, csv_text: str) -> tuple[dict | None, list[dict]]:
    """Return (event_row, track_point_rows) for one flight CSV.

    ``event_row`` is None for an empty/headerless file.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    points: list[dict] = []
    callsign = ""
    first_pos = last_pos = ""
    max_alt: int | None = None
    max_speed: int | None = None
    first_at = ""
    event_id = f"adsb-{file_id}"

    for row in reader:
        cs = (row.get("Callsign") or "").strip()
        if cs and not callsign:
            callsign = cs
        pos = (row.get("Position") or "").strip()
        lat, lng = _split_position(pos)
        at = (row.get("UTC") or "").strip()
        if not first_at and at:
            first_at = at
        if pos:
            if not first_pos:
                first_pos = pos
            last_pos = pos

        def _int(val):
            try:
                return int(float(val))
            except (TypeError, ValueError):
                return None

        alt = _int(row.get("Altitude"))
        spd = _int(row.get("Speed"))
        if alt is not None:
            max_alt = alt if max_alt is None else max(max_alt, alt)
        if spd is not None:
            max_speed = spd if max_speed is None else max(max_speed, spd)

        ts = _int(row.get("Timestamp"))
        if ts is None:
            continue  # ts is part of the track_points primary key
        points.append({
            "flight_id": event_id,
            "ts": ts,
            "at": at,
            "lat": lat,
            "lng": lng,
            "altitude_ft": alt,
            "speed": spd,
            "direction": _int(row.get("Direction")),
        })

    if not points and not callsign:
        return None, []

    aircraft_type, operator = KNOWN_AIRCRAFT.get(callsign, ("", ""))
    event_row = {
        "id": event_id,
        "at": first_at,
        "callsign": callsign,
        "registration": callsign,
        "aircraft_type": aircraft_type,
        "operator": operator,
        "origin_code": first_pos,
        "destination_code": last_pos,
        "altitude_ft": max_alt if max_alt is not None else "",
        "ground_speed_mph": max_speed if max_speed is not None else "",
        "flight_status": f"{len(points)} ADS-B points",
        "image_path": "",
        "label": callsign or f"ADS-B flight {file_id}",
    }
    return event_row, points


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ingest a per-tail ADS-B archive into priis.db"
    )
    ap.add_argument("--zip", help="Path to the archive zip")
    ap.add_argument("--dir", help="Path to an extracted archive directory")
    ap.add_argument("--db", default=str(DB_DEFAULT), help="Path to priis.db")
    ap.add_argument("--events-csv", default=str(EVENTS_CSV_DEFAULT),
                    help="Where to write the FR24-compatible events CSV")
    ap.add_argument("--watchlist", default=str(WATCHLIST_DEFAULT),
                    help="Registration watchlist YAML")
    ap.add_argument("--no-alerts", action="store_true",
                    help="Skip registration alert generation")
    args = ap.parse_args()

    if not args.zip and not args.dir:
        ap.error("one of --zip or --dir is required")
    source = Path(args.dir or args.zip)
    if not source.exists():
        ap.error(f"source not found: {source}")

    events: list[dict] = []
    track_rows: list[dict] = []
    by_tail: dict[str, int] = {}
    for file_id, csv_text in iter_flight_csvs(source):
        event_row, points = parse_flight(file_id, csv_text)
        if event_row is None:
            continue
        events.append(event_row)
        track_rows.extend(points)
        by_tail[event_row["callsign"] or "?"] = (
            by_tail.get(event_row["callsign"] or "?", 0) + 1
        )

    events.sort(key=lambda e: e["id"])
    events_csv = Path(args.events_csv)
    events_csv.parent.mkdir(parents=True, exist_ok=True)
    with events_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EVENT_CSV_FIELDS)
        w.writeheader()
        w.writerows(events)

    print(f"Parsed {len(events)} flights / {len(track_rows)} track points")
    for tail in sorted(by_tail):
        print(f"  {tail}: {by_tail[tail]} flights")
    print(f"Events CSV → {events_csv}")

    conn = _connect(args.db)
    try:
        run_migrations(conn)
        n_events = ingest_fr24_csv(conn, events_csv)
        n_points = ingest_track_points(conn, track_rows)
        print(f"Ingested {n_events} events, {n_points} new track points → {args.db}")

        if not args.no_alerts:
            watchlist = load_watchlist(Path(args.watchlist))
            summary = generate_alerts(conn, watchlist)
            print(
                f"Alerts: watchlist={summary['watchlist_size']} "
                f"seen={summary['seen_matches']} missing={summary['missing_matches']} "
                f"new_alerts={summary['new_alerts']} notified={summary['notified']}"
            )
    finally:
        conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
