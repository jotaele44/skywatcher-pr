"""Route cluster summaries for SATIM track ledgers."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

from .util import safe_float, stable_id


def _bucket(latitude: float, longitude: float, precision: int = 2) -> str:
    """Return a coarse spatial bucket key."""

    return f"{round(latitude, precision):.{precision}f},{round(longitude, precision):.{precision}f}"


def _is_visual_estimate(row: dict[str, str]) -> bool:
    """Classify visual-estimate rows using provenance/source hints only."""

    provenance = row.get("provenance_level", "").lower()
    source = row.get("source", "").lower()
    return "visual" in provenance or source.endswith((".png", ".jpg", ".jpeg", ".heic", ".pdf"))


def build_route_cluster_summary(track_rows: tuple[dict[str, str], ...]) -> list[dict[str, object]]:
    """Summarize recurring route geometry by source and coarse spatial bucket."""

    groups: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in track_rows:
        lat = safe_float(row.get("latitude"))
        lon = safe_float(row.get("longitude"))
        source = row.get("source", "")
        row_class = "visual_estimate" if _is_visual_estimate(row) else "coordinate_track"
        groups[(source, _bucket(lat, lon), row_class)].append(row)

    output: list[dict[str, object]] = []
    for (source, spatial_bucket, row_class), rows in groups.items():
        scores = [safe_float(row.get("verification_score")) for row in rows]
        timestamps = sorted(row.get("timestamp", "") for row in rows if row.get("timestamp"))
        output.append(
            {
                "cluster_id": stable_id("cluster", source, spatial_bucket, row_class),
                "source": source,
                "spatial_bucket": spatial_bucket,
                "row_class": row_class,
                "row_count": len(rows),
                "verification_score_avg": round(mean(scores), 3) if scores else 0.0,
                "verification_score_min": round(min(scores), 3) if scores else 0.0,
                "verification_score_max": round(max(scores), 3) if scores else 0.0,
                "first_timestamp": timestamps[0] if timestamps else "",
                "last_timestamp": timestamps[-1] if timestamps else "",
            }
        )
    return sorted(output, key=lambda row: (str(row["source"]), str(row["spatial_bucket"]), str(row["row_class"])))
