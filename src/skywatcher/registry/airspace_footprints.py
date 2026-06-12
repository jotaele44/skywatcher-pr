"""Load Puerto Rico airspace footprint and helipad registries."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class AirspaceFootprint:
    footprint_id: str
    airfield_code: str
    facility_name: str
    facility_type: str
    operator_class: str
    latitude: float | None
    longitude: float | None
    radius_m: int
    confidence: str
    source_tier: str
    description: str


def _to_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def load_airspace_footprints(path: str | Path) -> list[AirspaceFootprint]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [
            AirspaceFootprint(
                footprint_id=row["footprint_id"],
                airfield_code=row["airfield_code"],
                facility_name=row["facility_name"],
                facility_type=row["facility_type"],
                operator_class=row["operator_class"],
                latitude=_to_float(row.get("latitude")),
                longitude=_to_float(row.get("longitude")),
                radius_m=int(row["radius_m"]),
                confidence=row["confidence"],
                source_tier=row["source_tier"],
                description=row.get("description", ""),
            )
            for row in reader
        ]


def load_helipads(path: str | Path) -> list[AirspaceFootprint]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [
            AirspaceFootprint(
                footprint_id=row["helipad_id"],
                airfield_code=row["faa_code"],
                facility_name=row["name"],
                facility_type="helipad",
                operator_class=row["operator_class"],
                latitude=_to_float(row.get("latitude")),
                longitude=_to_float(row.get("longitude")),
                radius_m=int(row["radius_m"]),
                confidence=row["confidence"],
                source_tier=row["source_tier"],
                description=row.get("description", ""),
            )
            for row in reader
        ]
