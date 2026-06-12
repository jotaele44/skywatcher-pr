#!/usr/bin/env python3
"""Import Puerto Rico airspace footprint reference data.

The importer preserves every source row as either a normalized airspace footprint
or a normalized helipad record. It does not fabricate geometry. Airport tenants
without explicit coordinates are emitted as G0 fallback nodes requiring geometry
review. Helipads with coordinates embedded in the location field are emitted as
G1 point nodes.
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

REQUIRED_COLUMNS = {
    "airfield",
    "facility_name",
    "facility_type",
    "organization",
    "location",
    "description",
    "citation",
}

AIRFIELD_NAME_MAP = {
    "SIG": "Fernando Luis Ribas Dominicci Airport",
    "SJU": "Luis Munoz Marin International Airport",
    "BQN": "Rafael Hernandez International Airport",
    "PSE": "Mercedita International Airport",
    "TJRV": "Jose Aponte de la Torre Airport",
    "MAZ": "Eugenio Maria de Hostos Airport",
    "ARE": "Antonio Nery Juarbe Pol Airport",
}

MUNICIPALITY_MAP = {
    "SIG": "San Juan",
    "SJU": "Carolina",
    "BQN": "Aguadilla",
    "PSE": "Ponce",
    "TJRV": "Ceiba",
    "MAZ": "Mayaguez",
    "ARE": "Arecibo",
}

AIRFIELD_CODES = ["TJRV", "SJU", "SIG", "BQN", "PSE", "MAZ", "ARE"]

FOOTPRINT_FIELDS = [
    "footprint_id",
    "airfield_code",
    "airfield_name",
    "municipality",
    "facility_name",
    "organization_name",
    "facility_type",
    "operator_class",
    "aviation_roles",
    "location_text",
    "latitude",
    "longitude",
    "radius_m",
    "geometry_level",
    "geometry_wkt",
    "geometry_confidence",
    "confidence",
    "needs_geometry",
    "needs_manual_verification",
    "source_tier",
    "source_citations",
    "last_verified",
    "description",
]

HELIPAD_FIELDS = [
    "helipad_id",
    "faa_code",
    "name",
    "organization_name",
    "operator_class",
    "location_text",
    "latitude",
    "longitude",
    "radius_m",
    "confidence",
    "source_tier",
    "source_citations",
    "last_verified",
    "description",
]


def slug(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "unknown"


def extract_airfield_code(airfield: str) -> str:
    for code in AIRFIELD_CODES:
        if re.search(rf"\b{re.escape(code)}\b", airfield):
            return code
    match = re.search(r"\(([A-Z0-9]{3,4})\)", airfield)
    return match.group(1) if match else "UNK"


def extract_helipad_code(airfield: str, facility_name: str) -> str:
    combined = f"{airfield} {facility_name}"
    match = re.search(r"\b([0-9]{1,2}PR|PR[0-9]{2}|[A-Z0-9]{4})\b", combined)
    return match.group(1) if match else "UNK"


def parse_coordinates(location: str) -> tuple[str, str]:
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", location)
    if not match:
        return "", ""
    return match.group(1), match.group(2)


def normalize_facility_type(raw_type: str, facility_name: str) -> str:
    text = f"{raw_type} {facility_name}".lower()
    if "helipad" in text or "heliport" in text:
        return "helipad"
    if "law" in text or "cbp" in text or "border" in text:
        return "law_enforcement_air"
    if "military" in text or "national guard" in text:
        return "military_unit"
    if "coast guard" in text or "government" in text:
        return "government_aviation"
    if "weather" in text:
        return "weather_office"
    if "postal" in text or "usps" in text:
        return "postal_facility"
    if "cargo carrier" in text:
        return "cargo_carrier"
    if "cargo" in text:
        return "cargo_facility"
    if "school" in text or "training" in text:
        return "flight_school"
    if "mro" in text or "maintenance" in text:
        return "mro"
    if "fbo" in text:
        return "fbo"
    if "airport operations" in text:
        return "airport_operations"
    return "unknown_airspace_org"


def normalize_operator_class(facility_type: str, org: str, description: str) -> str:
    text = f"{facility_type} {org} {description}".lower()
    if facility_type == "helipad":
        if "hospital" in text or "health" in text or "medico" in text:
            return "medical"
        if "army" in text or "fort" in text:
            return "federal_dod"
        if "aqueduct" in text or "sewer" in text:
            return "utility_infrastructure"
        if "baxter" in text:
            return "private_industrial"
        return "unknown"
    if "customs" in text or "border protection" in text or "dhs" in text:
        return "federal_dhs"
    if "coast guard" in text:
        return "federal_dhs"
    if "national guard" in text or "army" in text:
        return "federal_dod"
    if "weather" in text or "noaa" in text:
        return "federal_noaa"
    if "postal" in text or "usps" in text or "fedex" in text or "dhl" in text or "cargo" in text or "kingfisher" in text:
        return "commercial_logistics"
    if "technik" in text or "mro" in text or "repair" in text or "maintenance" in text:
        return "maintenance_repair_overhaul"
    if "school" in text or "university" in text or "benitez" in text:
        return "flight_training" if "university" not in text else "academic"
    if "fbo" in text or "aviation services" in text or "jet center" in text:
        return "commercial_fbo"
    if "ports authority" in text:
        return "airport_authority"
    if "health" in text or "hospital" in text:
        return "medical"
    return "unknown"


def default_radius(facility_type: str, geometry_level: str) -> int:
    if facility_type == "helipad":
        return 100
    if facility_type in {"fbo", "mro", "flight_school"}:
        return 250
    if facility_type in {"cargo_facility", "cargo_carrier"}:
        return 300
    if facility_type in {"government_aviation", "military_unit", "law_enforcement_air"}:
        return 500
    if geometry_level == "G0":
        return 1500
    return 250


def row_to_footprint(row: dict[str, str], verified: str) -> dict[str, str | int | bool]:
    code = extract_airfield_code(row["airfield"])
    facility_type = normalize_facility_type(row["facility_type"], row["facility_name"])
    operator_class = normalize_operator_class(facility_type, row["organization"], row["description"])
    lat, lon = parse_coordinates(row["location"])
    geometry_level = "G1" if lat and lon else "G0"
    fid = f"pr-{slug(code)}-{slug(row['facility_name'])}"
    return {
        "footprint_id": fid,
        "airfield_code": code,
        "airfield_name": AIRFIELD_NAME_MAP.get(code, row["airfield"]),
        "municipality": MUNICIPALITY_MAP.get(code, ""),
        "facility_name": row["facility_name"],
        "organization_name": row["organization"],
        "facility_type": facility_type,
        "operator_class": operator_class,
        "aviation_roles": facility_type,
        "location_text": row["location"],
        "latitude": lat,
        "longitude": lon,
        "radius_m": default_radius(facility_type, geometry_level),
        "geometry_level": geometry_level,
        "geometry_wkt": f"POINT ({lon} {lat})" if lat and lon else "",
        "geometry_confidence": "high" if geometry_level == "G1" else "low",
        "confidence": "high" if row["citation"].strip() else "medium",
        "needs_geometry": geometry_level == "G0",
        "needs_manual_verification": facility_type == "unknown_airspace_org" or geometry_level == "G0",
        "source_tier": "T2",
        "source_citations": row["citation"],
        "last_verified": verified,
        "description": row["description"],
    }


def row_to_helipad(row: dict[str, str], verified: str) -> dict[str, str | int]:
    faa_code = extract_helipad_code(row["airfield"], row["facility_name"])
    lat, lon = parse_coordinates(row["location"])
    operator_class = normalize_operator_class("helipad", row["organization"], row["description"])
    return {
        "helipad_id": f"pr-{slug(faa_code)}-{slug(row['facility_name'])}",
        "faa_code": faa_code,
        "name": row["facility_name"],
        "organization_name": row["organization"],
        "operator_class": operator_class,
        "location_text": row["location"],
        "latitude": lat,
        "longitude": lon,
        "radius_m": 100,
        "confidence": "high" if lat and lon else "medium",
        "source_tier": "T2",
        "source_citations": row["citation"],
        "last_verified": verified,
        "description": row["description"],
    }


def read_source(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")
        return [{k: (v or "").strip() for k, v in row.items()} for row in reader]


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


def write_report(path: Path, source_count: int, footprints: list[dict[str, object]], helipads: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_geometry = sum(1 for row in footprints if row.get("needs_geometry") is True)
    report = f"""# Puerto Rico Airspace Footprint Import Report

## Summary

| Metric | Count |
|---|---:|
| Source rows | {source_count} |
| Footprints | {len(footprints)} |
| Helipads | {len(helipads)} |
| Rejected rows | 0 |
| Footprints needing geometry | {needs_geometry} |

## Coverage Rules

- 100% of source rows must be preserved as a normalized footprint or helipad.
- No coordinates are fabricated.
- Airport tenants without explicit coordinates are G0 fallback nodes and require manual polygon review.
- Helipads with embedded coordinates are G1 point nodes.

## Blind Spots

1. Public records do not prove complete tenant occupancy for every hangar or sublease.
2. Facility geometry for most FBOs, cargo ramps, MROs, and government compounds requires manual polygoning.
3. FURA / Puerto Rico Police aviation footprints require a second source and direct geometry confirmation.
4. Helipad records should be reconciled against FAA NASR/NFDC before operational use.
"""
    path.write_text(report, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/reference/puerto_rico_airfields_dataset.csv")
    parser.add_argument("--footprints-out", default="registry/puerto_rico_airspace_footprints.csv")
    parser.add_argument("--helipads-out", default="registry/puerto_rico_helipads.csv")
    parser.add_argument("--report", default="reports/pr_airspace_footprint_import.md")
    parser.add_argument("--last-verified", default=date.today().isoformat())
    args = parser.parse_args()

    rows = read_source(Path(args.input))
    footprints: list[dict[str, object]] = []
    helipads: list[dict[str, object]] = []

    for row in rows:
        normalized_type = normalize_facility_type(row["facility_type"], row["facility_name"])
        if normalized_type == "helipad":
            helipads.append(row_to_helipad(row, args.last_verified))
        else:
            footprints.append(row_to_footprint(row, args.last_verified))

    write_csv(Path(args.footprints_out), FOOTPRINT_FIELDS, footprints)
    write_csv(Path(args.helipads_out), HELIPAD_FIELDS, helipads)
    write_report(Path(args.report), len(rows), footprints, helipads)
    print(f"imported source_rows={len(rows)} footprints={len(footprints)} helipads={len(helipads)} rejected=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
