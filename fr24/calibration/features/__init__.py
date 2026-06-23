"""SATIM L0-L4 feature generation for synthetic boundary calibration.

Feature modules intentionally emit normalized scores only. Classification happens in
``fr24.calibration.l5_synthetic_boundary_classifier`` so rejection logic remains
weighted, auditable, and calibration-friendly.
"""

from .boundary_geometry import BoundaryGeometryFeatures, compute_boundary_geometry_features
from .infrastructure_features import InfrastructureFeatures, compute_infrastructure_features
from .landcover_features import LandcoverFeatures, compute_landcover_features
from .radiometric_features import RadiometricFeatures, compute_radiometric_features
from .terrain_features import TerrainFeatures, compute_terrain_features

__all__ = [
    "BoundaryGeometryFeatures",
    "InfrastructureFeatures",
    "LandcoverFeatures",
    "RadiometricFeatures",
    "TerrainFeatures",
    "compute_boundary_geometry_features",
    "compute_infrastructure_features",
    "compute_landcover_features",
    "compute_radiometric_features",
    "compute_terrain_features",
]
