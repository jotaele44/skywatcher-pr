"""Tests for the parallax / rectilinear mosaic-seam geometry add-on."""

from __future__ import annotations

import pytest

from satim_calibration import promotion_decision
from satim_geometry import (
    EdgeFeature,
    cap_decision_for_geometry,
    detect_seam_box,
    expected_parallax_m,
    is_axis_aligned,
    is_geometry_coherent,
    is_rectilinear_seam,
    parallax_coherence,
    seam_confidence,
)

DEFAULT_THRESHOLDS = {
    "review": 0.55,
    "cross_source_required": 0.70,
    "promote_to_candidate": 0.80,
}


# --- parallax ----------------------------------------------------------------
class TestParallax:
    def test_expected_parallax_scales_with_speed_and_time(self):
        assert expected_parallax_m(60, 2) == pytest.approx(60 * 0.44704 * 2)
        assert expected_parallax_m(0, 2) == 0.0

    def test_moving_ground_feature_is_coherent(self):
        assert parallax_coherence(expected_parallax_m(52, 2), 52, 2) is True

    def test_screen_locked_feature_is_incoherent(self):
        assert parallax_coherence(0.5, 52, 2) is False

    def test_no_motion_is_uninformative(self):
        assert parallax_coherence(0.0, 0, 2) is True

    def test_altitude_envelope_gate(self):
        envelope = [800, 850, 900, 925]
        assert is_geometry_coherent(
            expected_parallax_m(52, 2), ground_speed_mph=52, dt_s=2,
            altitude_ft=850, altitude_envelope=envelope,
        ) is True
        assert is_geometry_coherent(
            expected_parallax_m(52, 2), ground_speed_mph=52, dt_s=2,
            altitude_ft=5000, altitude_envelope=envelope,
        ) is False


# --- rectilinear seam --------------------------------------------------------
class TestSeamDetection:
    def _seam(self, orientation_deg, observed_shift_m=1.0):
        return EdgeFeature(
            orientation_deg=orientation_deg, straightness=0.95, tonal_delta=0.30,
            observed_shift_m=observed_shift_m, ground_speed_mph=52, dt_s=2,
        )

    def test_axis_alignment(self):
        assert is_axis_aligned(3.0)
        assert is_axis_aligned(88.0)
        assert is_axis_aligned(179.0)
        assert not is_axis_aligned(45.0)

    def test_seam_edge_detected(self):
        assert is_rectilinear_seam(self._seam(2.0)) is True

    def test_terrain_edge_is_not_a_seam(self):
        moving = EdgeFeature(
            orientation_deg=2.0, straightness=0.95, tonal_delta=0.30,
            observed_shift_m=expected_parallax_m(52, 2), ground_speed_mph=52, dt_s=2,
        )
        assert is_rectilinear_seam(moving) is False

    def test_diagonal_edge_is_not_a_seam(self):
        assert is_rectilinear_seam(self._seam(45.0)) is False

    def test_no_tonal_break_is_not_a_seam(self):
        flat = EdgeFeature(
            orientation_deg=2.0, straightness=0.95, tonal_delta=0.02,
            observed_shift_m=1.0, ground_speed_mph=52, dt_s=2,
        )
        assert is_rectilinear_seam(flat) is False

    def test_seam_confidence_ranks_screen_locked_above_zero(self):
        assert seam_confidence(self._seam(2.0)) == pytest.approx(0.95 * 0.30)
        assert seam_confidence(self._seam(45.0)) == 0.0

    def test_detect_seam_box_needs_two_orientations(self):
        assert detect_seam_box([self._seam(1.0), self._seam(90.0)]) is True
        assert detect_seam_box([self._seam(1.0)]) is False
        assert detect_seam_box([self._seam(1.0), self._seam(2.0)]) is False


# --- engine integration ------------------------------------------------------
class TestGeometryGate:
    def test_incoherent_geometry_caps_candidate_at_review(self):
        decision = promotion_decision(0.95, DEFAULT_THRESHOLDS)
        assert decision == "candidate"
        assert cap_decision_for_geometry(decision, False) == "review"

    def test_coherent_or_unknown_leaves_decision_untouched(self):
        decision = promotion_decision(0.95, DEFAULT_THRESHOLDS)
        assert cap_decision_for_geometry(decision, True) == "candidate"
        assert cap_decision_for_geometry(decision, None) == "candidate"

    def test_suppressed_stays_suppressed(self):
        assert cap_decision_for_geometry("suppressed", False) == "suppressed"

    def test_detected_seam_caps_promotion(self):
        seam = EdgeFeature(
            orientation_deg=2.0, straightness=0.95, tonal_delta=0.30,
            observed_shift_m=1.0, ground_speed_mph=52, dt_s=2,
        )
        coherent = not is_rectilinear_seam(seam)
        capped = cap_decision_for_geometry(promotion_decision(0.95, DEFAULT_THRESHOLDS), coherent)
        assert coherent is False
        assert capped == "review"
