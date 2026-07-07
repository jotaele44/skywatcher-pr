"""Grid key helpers for GATIM."""
from __future__ import annotations


def grid_id_for(lat: str | float, lon: str | float, precision: int = 3) -> str:
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return "NO_GRID"
    return f"GRID_{round(lat_f, precision):.{precision}f}_{round(lon_f, precision):.{precision}f}"
