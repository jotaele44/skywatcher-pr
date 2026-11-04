"""Star-field layers for the Sky Target Finder chart.

Everything is returned as apparent (refracted) altitude/azimuth around a centre;
the browser applies the gnomonic projection, so FOV and zoom changes need no
refetch. Stars are prefiltered by J2000 angular distance (with a margin for
refraction) before the per-star horizon transform.
"""

from __future__ import annotations

import math
from typing import Any

from .catalog import SkyCatalog, unit_vector
from .ephemeris import SkyFrame

# Refraction can move a point near the horizon by ~0.6 deg relative to its J2000 neighbours.
_PREFILTER_MARGIN_DEG = 1.0
# Constellation lines and labels reach past the chart edge so figures are not cut short.
_CONTEXT_MARGIN_DEG = 15.0
# Star labels are drawn for named stars at least this bright.
LABEL_MAG_LIMIT = 5.0
# The deep (mag 6-7.5) layer is only worth sending for narrow fields of view.
DEEP_LAYER_MAX_FOV_DEG = 15.0


def horizontal_separation(alt1: float, az1: float, alt2: float, az2: float) -> float:
    """Great-circle angle (degrees) between two alt/az directions."""
    a1, a2 = math.radians(alt1), math.radians(alt2)
    cos_c = math.sin(a1) * math.sin(a2) + math.cos(a1) * math.cos(a2) * math.cos(
        math.radians(az1 - az2)
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_c))))


def _cos_limit(radius_deg: float) -> float:
    return math.cos(math.radians(min(180.0, radius_deg)))


def build_chart_layers(
    catalog: SkyCatalog,
    frame: SkyFrame,
    *,
    center_ra: float,
    center_dec: float,
    center_alt: float,
    center_az: float,
    fov_deg: float,
    radius_deg: float,
    exclude_id: str | None = None,
) -> dict[str, Any]:
    """Stars, constellation figures/labels and DSO markers around a chart centre."""
    cx, cy, cz = unit_vector(center_ra, center_dec)
    near = _cos_limit(radius_deg + _PREFILTER_MARGIN_DEG)
    context = _cos_limit(radius_deg + _CONTEXT_MARGIN_DEG)

    def within(alt: float, az: float, limit: float) -> bool:
        return horizontal_separation(alt, az, center_alt, center_az) <= limit

    stars: list[dict[str, Any]] = []
    for (hip, ra, dec, mag), (x, y, z) in zip(catalog.stars, catalog.star_vectors, strict=True):
        if x * cx + y * cy + z * cz < near:
            continue
        alt, az, _ = frame.horizontal(ra, dec)
        if not within(alt, az, radius_deg):
            continue
        label = catalog.star_labels.get(hip) if mag <= LABEL_MAG_LIMIT else None
        stars.append(
            {"alt": round(alt, 3), "az": round(az, 3), "mag": mag,
             "id": f"star:hip:{hip}", "label": label}
        )
    include_deep = fov_deg <= DEEP_LAYER_MAX_FOV_DEG
    if include_deep:
        for (ra, dec, mag), (x, y, z) in zip(
            catalog.deep_stars, catalog.deep_star_vectors, strict=True
        ):
            if x * cx + y * cy + z * cz < near:
                continue
            alt, az, _ = frame.horizontal(ra, dec)
            if within(alt, az, radius_deg):
                stars.append(
                    {"alt": round(alt, 3), "az": round(az, 3), "mag": mag,
                     "id": None, "label": None}
                )
    stars.sort(key=lambda star: star["mag"])

    lines: list[dict[str, Any]] = []
    for figure in catalog.constellation_lines:
        for polyline in figure["lines"]:
            if not any(
                _dot(unit_vector(ra, dec), (cx, cy, cz)) >= context for ra, dec in polyline
            ):
                continue
            points = []
            for ra, dec in polyline:
                alt, az, _ = frame.horizontal(ra, dec)
                points.append([round(alt, 3), round(az, 3)])
            lines.append({"constellation": figure["id"], "points": points})

    labels = []
    for constellation in catalog.constellations:
        ra, dec = constellation["label_ra_deg"], constellation["label_dec_deg"]
        if _dot(unit_vector(ra, dec), (cx, cy, cz)) < context:
            continue
        alt, az, _ = frame.horizontal(ra, dec)
        labels.append({"id": constellation["id"], "name": constellation["name"],
                       "alt": round(alt, 3), "az": round(az, 3)})

    markers = []
    for item in catalog.objects:
        if item.kind == "star" or item.id == exclude_id:
            continue
        if _dot(unit_vector(item.ra_deg, item.dec_deg), (cx, cy, cz)) < near:
            continue
        alt, az, _ = frame.horizontal(item.ra_deg, item.dec_deg)
        if not within(alt, az, radius_deg):
            continue
        markers.append(
            {
                "id": item.id,
                "designation": item.designation,
                "long_designation": item.long_designation,
                "name": item.name,
                "alt": round(alt, 3),
                "az": round(az, 3),
                "size_arcmin": list(item.size_arcmin) if item.size_arcmin else None,
            }
        )

    return {
        "limiting_magnitude": 7.5 if include_deep else 6.0,
        "stars": stars,
        "lines": lines,
        "constellation_labels": labels,
        "dso_markers": markers,
    }


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
