from fr24.segment_provenance import SegmentSignals, assess_segment


def test_bright_offline_not_vetoed():
    result = assess_segment(SegmentSignals(
        temporal_gap=1.0,
        interpolation_geometry=1.0,
        sampling_density_deficit=0.9,
        endpoint_discontinuity=0.8,
        route_color="green",
        screenshot_only=True,
    ))
    assert result.final_classification == "PROBABLE_OFFLINE"
    assert result.visual_render_state == "BRIGHT_ROUTE"
    assert result.confidence <= 0.79


def test_dark_offline_adds_weak_support():
    result = assess_segment(SegmentSignals(
        temporal_gap=1.0,
        interpolation_geometry=1.0,
        sampling_density_deficit=0.9,
        endpoint_discontinuity=0.8,
        dark_gap_rendering=1.0,
        route_color="dark",
    ))
    assert result.final_classification == "PROBABLE_OFFLINE"
    assert result.visual_render_state == "DARK_ROUTE"


def test_legitimate_straight_continuous_track():
    result = assess_segment(SegmentSignals(
        interpolation_geometry=0.95,
        continuous_structured_track=True,
        route_color="green",
    ))
    assert result.final_classification == "OBSERVED_TRACK"


def test_source_fusion_not_mislabeled_offline():
    result = assess_segment(SegmentSignals(
        temporal_gap=0.8,
        source_transition=1.0,
        alternate_source_continuity=True,
        route_color="green",
    ))
    assert result.final_classification == "SOURCE_TRANSITION"
    assert result.transmission_state == "NOT_ASSESSABLE"


def test_sparse_sampling_is_interpolated_not_confirmed():
    result = assess_segment(SegmentSignals(
        interpolation_geometry=0.9,
        sampling_density_deficit=0.9,
        endpoint_discontinuity=0.7,
        route_color="green",
    ))
    assert result.final_classification == "INTERPOLATED"


def test_corroboration_unlocks_confirmed_offline():
    result = assess_segment(SegmentSignals(
        temporal_gap=0.8,
        corroborated_offline=True,
        route_color="green",
    ))
    assert result.final_classification == "CONFIRMED_OFFLINE"
    assert result.confidence >= 0.82


def test_dark_color_alone_does_not_make_offline():
    result = assess_segment(SegmentSignals(dark_gap_rendering=1.0, route_color="dark"))
    assert result.final_classification == "UNKNOWN"
