"""Read-only SATIM/GATIM interface helpers.

The interface only emits candidate links. It does not assert flight causation or site confirmation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .gatim_dedupe import haversine_m


@dataclass
class SATIMGATIMLink:
    gatim_id: str
    fn_id: str
    grid_id: str
    distance_m: float
    link_status: str
    confidence_delta: float


def link_to_fn_points(gatim_rows: Iterable, fn_points: Iterable[dict], radius_m: float = 250.0) -> list[SATIMGATIMLink]:
    links: list[SATIMGATIMLink] = []
    for row in gatim_rows:
        try:
            glat, glon = float(row.lat), float(row.lon)
        except (TypeError, ValueError):
            continue
        for fn in fn_points:
            try:
                flat, flon = float(fn["lat"]), float(fn["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            distance = haversine_m(glat, glon, flat, flon)
            if distance <= radius_m:
                status = "confirmed_overlap" if distance <= 25 else "nearby_FN"
                links.append(
                    SATIMGATIMLink(
                        gatim_id=row.gatim_id,
                        fn_id=str(fn.get("fn_id", "FN_UNKNOWN")),
                        grid_id=row.grid_id,
                        distance_m=round(distance, 2),
                        link_status=status,
                        confidence_delta=0.05 if status == "nearby_FN" else 0.10,
                    )
                )
    return links


def links_as_dicts(links: Iterable[SATIMGATIMLink]) -> list[dict]:
    return [asdict(link) for link in links]
