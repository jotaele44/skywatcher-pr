from fr24.calibration.features.boundary_geometry import compute_boundary_geometry_features
from fr24.calibration.features.infrastructure_features import compute_infrastructure_features
from fr24.calibration.features.landcover_features import compute_landcover_features
from fr24.calibration.features.terrain_features import compute_terrain_features


def test_boundary_geometry_scores_straight_polyline() -> None:
    features = compute_boundary_geometry_features({"boundary_points": "0:0;10:0;20:0"})
    assert features.straightness == 1.0
    assert features.segment_count == 2


def test_boundary_geometry_scores_orthogonal_turn_as_weak_feature() -> None:
    features = compute_boundary_geometry_features({"boundary_points": "0:0;10:0;10:10"})
    assert features.orthogonality == 1.0
    assert features.straightness < 1.0


def test_infrastructure_alignment_is_weighted_not_binary() -> None:
    features = compute_infrastructure_features({"road_alignment": "1.0", "building_alignment": "0.2"})
    assert 0.0 < features.infrastructure_rejection < 1.0
    assert features.road_alignment == 1.0


def test_terrain_crossing_high_when_surface_varies_and_boundary_is_straight() -> None:
    features = compute_terrain_features({"terrain_profile": "0,50,120,35,90", "straightness": "0.98"})
    assert features.terrain_crossing > 0.3


def test_landcover_persistence_and_coastal_crossing() -> None:
    features = compute_landcover_features({"landcover_classes": "forest,grass,urban,beach,reef,water", "boundary_continuity": "0.95"})
    assert features.landcover_persistence > 0.8
    assert features.coastal_crossing_score > 0.0
