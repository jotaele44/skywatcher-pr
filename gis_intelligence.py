"""Backward-compat shim. Logic moved to skywatcher.corrim.gis_intelligence.
See docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""
from __future__ import annotations

from skywatcher.corrim.gis_intelligence import (
    AnomalyDetector,
    CorridorAnalyzer,
    FlightCorridor,
    HeatmapGenerator,
    InfrastructureFeature,
    InfrastructureType,
    Phase2Database,
    PuertoRicoInfrastructure,
    _kml_color,
    haversine_nm,
    intensity_to_color,
    point_to_line_distance,
)

__all__ = [
    "AnomalyDetector",
    "CorridorAnalyzer",
    "FlightCorridor",
    "HeatmapGenerator",
    "InfrastructureFeature",
    "InfrastructureType",
    "Phase2Database",
    "PuertoRicoInfrastructure",
    "haversine_nm",
    "intensity_to_color",
    "point_to_line_distance",
]

if __name__ == "__main__":
    print("Phase 2 GIS Intelligence Layer loaded.")
    infra = PuertoRicoInfrastructure()
    print(f"  {len(infra.features)} infrastructure features defined")
