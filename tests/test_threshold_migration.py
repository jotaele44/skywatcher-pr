"""Constants migrated onto the governed threshold registry.

The migrated values are unchanged; what changes is that each now carries an owner,
status, validation artifact and failure behavior, and stamps its provenance into output.
These tests pin both halves: the numbers did not move, and the provenance is present.
"""

from __future__ import annotations

import pytest

from skywatcher.core.lenses import ThresholdNotExecutable, default_registry
from skywatcher.corrim.ilap_airspace_bridge import CONFIDENCE_WEIGHTS, GRID_DEG
from skywatcher.fusion import anomaly_scoring


def test_ilap_weights_are_unchanged_by_the_migration() -> None:
    assert CONFIDENCE_WEIGHTS == {
        "recurrence": 0.30,
        "loiter": 0.25,
        "infra_align": 0.20,
        "hydro_utility": 0.15,
        "mbil_proximity": 0.10,
    }
    assert GRID_DEG == 0.05
    # Kept by tests/conftest.py too; restated here because the registry is now what
    # decides it, and a bad edit there would break the invariant from a distance.
    assert abs(sum(CONFIDENCE_WEIGHTS.values()) - 1.0) < 1e-9


def test_ilap_weights_resolve_through_the_registry() -> None:
    registry = default_registry()
    assert CONFIDENCE_WEIGHTS["recurrence"] == registry.value_of("ILAP-WEIGHT-RECURRENCE")
    assert CONFIDENCE_WEIGHTS["loiter"] == registry.value_of("ILAP-WEIGHT-LOITER")
    assert registry.value_of("ILAP-GRID-0.05DEG") == GRID_DEG


def test_identity_priority_stays_prohibited_and_unused() -> None:
    """The one rule the ontology bans outright must not have crept back in."""
    with pytest.raises(ThresholdNotExecutable):
        default_registry().value_of("ILAP-IDENTITY-PRIORITY")
    assert "identity" not in " ".join(CONFIDENCE_WEIGHTS).lower()


def test_anomaly_weights_and_bands_are_unchanged() -> None:
    registry = default_registry()
    assert registry.value_of(anomaly_scoring.RATIO_WEIGHT_ID) == 0.65
    assert registry.value_of(anomaly_scoring.CONFIDENCE_WEIGHT_ID) == 0.35
    assert registry.value_of(anomaly_scoring.BAND_HIGH_ID) == 0.80
    assert registry.value_of(anomaly_scoring.BAND_MODERATE_ID) == 0.60
    assert registry.value_of(anomaly_scoring.BAND_LOW_ID) == 0.40


@pytest.mark.parametrize(
    "score, band",
    [(0.95, "high_review"), (0.80, "high_review"), (0.65, "moderate_review"),
     (0.45, "low_review"), (0.10, "suppress")],
)
def test_band_boundaries_behave_exactly_as_before(score: float, band: str) -> None:
    assert anomaly_scoring._band(score) == band


def test_scored_rows_carry_the_thresholds_that_produced_them() -> None:
    """ADR v2.1 A2 - an executed threshold stamps its status into output."""
    scored = anomaly_scoring.score_against_historical_baselines(
        [{"corridor_id": "c1", "domain": "air", "event_count": 10, "confidence": 0.9}],
        [{"corridor_id": "c1", "domain": "air", "historical_count": 1}],
    )
    assert scored, "a 10x deviation should score above the suppression floor"

    stamps = {s["threshold_id"]: s for s in scored[0]["thresholds_applied"]}
    assert set(stamps) == set(anomaly_scoring.THRESHOLD_IDS)
    for stamp in stamps.values():
        assert stamp["status"] == "EXECUTABLE_CANDIDATE", (
            "these cutoffs are unvalidated, and the output must say so"
        )

    # The review-only posture is untouched by the migration.
    assert scored[0]["operator_action"] == "review_context_only"
    assert scored[0]["live_tracking"] is False
    assert scored[0]["operational_cueing"] is False
