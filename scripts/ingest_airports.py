#!/usr/bin/env python3
"""Materialize the real PR airport registry for the Skywatcher engine.

Source: ``Airport_Master_PR_seed_v1_3.geojson`` (19 curated PR airports with
ICAO/IATA, coords, municipality, runway, operational status — derived from FAA
NASR + public sources). Produces ``data/reference/pr_airports.jsonl``, the
ground-truth airport registry the airspace engine (aircraft_intelligence /
ilap_airspace_bridge) resolves against, replacing synthetic airport positions.

This is REFERENCE data only — the live airspace *observation* stream still
requires real FlightRadar24 capture (see federation.json readiness gate).

Source lives outside the repo; pass ``--src`` to override. The small registry
(19 rows) is committed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_SRC = "/Users/jotaele/Documents/Data/PR_Geodata/06_Vector_GeoJSON/Airport_Master_PR_seed_v1_3.geojson"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_registry(features: list) -> list:
    rows = []
    for f in features:
        p = f.get("properties") or {}
        g = f.get("geometry") or {}
        coords = g.get("coordinates")
        lat = _num(p.get("Latitude"))
        lon = _num(p.get("Longitude"))
        if lat is None and g.get("type") == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
            lon, lat = float(coords[0]), float(coords[1])
        rows.append({
            "airport_id": p.get("ICAO") or p.get("UID") or p.get("IATA") or p.get("Canonical_Name"),
            "name": p.get("Canonical_Name") or p.get("Name"),
            "icao": p.get("ICAO"),
            "iata": p.get("IATA"),
            "lat": lat,
            "lon": lon,
            "municipality": p.get("Municipality"),
            "elevation_ft": _num(p.get("Elevation_ft")),
            "runway_length_m": _num(p.get("Runway_Length_m")),
            "runway_surface": p.get("Runway_Surface"),
            "operational_status": p.get("Operational_Status"),
            "ownership": p.get("Ownership"),
            "landing_type": p.get("Landing_Type"),
            "confidence": _num(p.get("Confidence_Percent")),
            "source": "FAA NASR + Airport_Master_PR_seed",
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--out", default="data/reference/pr_airports.jsonl")
    args = ap.parse_args()

    doc = json.loads(Path(args.src).read_text())
    rows = build_registry(doc.get("features", []))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"wrote {len(rows)} airports -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
