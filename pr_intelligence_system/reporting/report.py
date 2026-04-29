import logging
import os
from datetime import datetime, timezone

import geopandas as gpd

logger = logging.getLogger(__name__)


def _terrain_line(mean_physics_score: float) -> str:
    if mean_physics_score > 0.75:
        return "Strong physics signal detected — terrain highly favourable for ILAP activity."
    if mean_physics_score > 0.55:
        return "Moderate terrain activity — mixed slope and elevation characteristics."
    return "Low terrain signal — area shows minimal physics-based indicators."


def _hydro_line(hydro_linked_count: int, mean_hydro_align: float) -> str:
    if hydro_linked_count > 0:
        return (
            f"Significant hydrological alignment detected "
            f"({hydro_linked_count} feature(s), mean align={mean_hydro_align:.3f})."
        )
    return "No hydrological linkage detected in this area."


def _corridor_line(corridor_count: int, corridor_ids: list) -> str:
    if corridor_count > 0:
        ids_str = ", ".join(str(c) for c in corridor_ids)
        return f"Present in {corridor_count} spatial corridor(s): [{ids_str}]."
    return "No corridor clustering observed in this area."


def build_report(
    lat: float,
    lon: float,
    radius_km: float,
    summary: dict,
    ilap_gdf: gpd.GeoDataFrame,
    aoi_id: str = "",
) -> str:
    """Generate a formatted ILAP Assessment Report string."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    total = summary.get("total_ilaps", 0)
    high_conf = summary.get("high_confidence_count", 0)
    hydro = summary.get("hydro_linked_count", 0)
    corr_ids = summary.get("corridor_ids", [])
    corr_count = summary.get("corridor_count", 0)
    mean_conf = summary.get("mean_confidence", 0.0)
    mean_phys = summary.get("mean_physics_score", 0.0)
    mean_hydro = summary.get("mean_hydro_align", 0.0)

    corridor_present = "YES" if corr_count > 0 else "NO"
    corridor_ids_str = str(corr_ids) if corr_ids else "None"

    lines = [
        "ILAP Assessment Report",
        "======================",
        f"Location: ({lat}, {lon})",
        f"Radius: {radius_km} km",
        f"AOI ID: {aoi_id}",
        f"Generated: {now}",
        "",
        f"Total ILAPs: {total}",
        f"High Confidence (>0.75): {high_conf}",
        f"Hydro-linked (hydro_align>0.50): {hydro}",
        f"Corridor Presence: {corridor_present}",
        f"Corridor IDs: {corridor_ids_str}",
        "",
        "Score Summary:",
        f"  Mean Physics Score  : {mean_phys:.3f}",
        f"  Mean Confidence     : {mean_conf:.3f}",
        f"  Mean Hydro Alignment: {mean_hydro:.3f}",
        "",
        "Interpretation:",
        f"- {_terrain_line(mean_phys)}",
        f"- {_hydro_line(hydro, mean_hydro)}",
        f"- {_corridor_line(corr_count, corr_ids)}",
    ]

    return "\n".join(lines)


def save_report(report_text: str, reports_dir: str, aoi_id: str) -> str:
    """Save report to reports_dir/{aoi_id}_{timestamp}.txt; return file path."""
    os.makedirs(reports_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{aoi_id}_{timestamp}.txt"
    path = os.path.join(reports_dir, filename)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(report_text)
    logger.info("Report saved to %s", path)
    return path
