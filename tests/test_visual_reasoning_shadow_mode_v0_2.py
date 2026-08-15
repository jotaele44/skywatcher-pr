from __future__ import annotations

from scripts.run_visual_reasoning_shadow_mode import run_shadow_mode


def test_shadow_mode_never_activates_production_and_preserves_source_identity() -> None:
    records = [
        {
            "source_id": "shadow-001",
            "kind": "shadow",
            "baseline_state": "SHADOW",
            "observation": {
                "darkness_ratio": 0.45,
                "local_deviation": 0.05,
                "texture_retention": 0.8,
                "edge_consistency": 0.8,
                "direction_delta_deg": 5.0,
                "clipped_black_ratio": 0.0,
                "geometry_support": True,
            },
        },
        {
            "source_id": "shadow-002",
            "kind": "shadow",
            "baseline_state": "SHADOW",
            "observation": {
                "darkness_ratio": 0.45,
                "local_deviation": 0.8,
                "texture_retention": 0.1,
                "edge_consistency": 0.2,
                "direction_delta_deg": 80.0,
                "clipped_black_ratio": 0.0,
                "geometry_support": False,
            },
        },
    ]
    parameters = {
        "SHADOW.DARKNESS_RATIO_MIN": 0.2,
        "SHADOW.DARKNESS_RATIO_MAX": 0.75,
        "SHADOW.LOCAL_DEVIATION_MAX": 0.2,
        "SHADOW.TEXTURE_RETENTION_MIN": 0.4,
        "SHADOW.DIRECTION_TOLERANCE_DEG": 20.0,
        "SHADOW.CLIPPED_BLACK_RATIO": 0.9,
    }
    report = run_shadow_mode(records, parameters)
    assert report["pass"] is True
    assert report["mode"] == "SHADOW_NON_ACTIVATING"
    assert [row["source_id"] for row in report["records"]] == ["shadow-001", "shadow-002"]
    assert all(row["production_activated"] is False for row in report["records"])
    assert report["records"][0]["canonical_state"] == "PHYSICALLY_PLAUSIBLE_SHADOW"
    assert report["records"][1]["canonical_state"] == "INCONSISTENT_SHADOW"


def test_shadow_mode_marks_fail_closed_demotion_as_more_conservative() -> None:
    records = [
        {
            "source_id": "artifact-001",
            "kind": "artifact",
            "baseline_state": "TRUE_SURFACE_FEATURE",
            "observation": {
                "render_scale_dependency": 0.4,
                "multiscale_persistence": 0.5,
                "multiframe_persistence": 0.5,
                "geometry_coherence": 0.5,
                "texture_coherence": 0.5,
                "lighting_coherence": 0.5,
                "pixel_grid_alignment": 0.4,
                "halo_or_ringing": 0.4,
            },
        }
    ]
    parameters = {
        "ARTIFACT.RENDER_SCALE_DEPENDENCY_MIN": 0.7,
        "ARTIFACT.MULTISCALE_PERSISTENCE_MIN": 0.65,
        "ARTIFACT.MULTIFRAME_PERSISTENCE_MIN": 0.65,
        "ARTIFACT.REAL_OBJECT_PROMOTION_MIN": 0.7,
        "ARTIFACT.ARTIFACT_PROMOTION_MIN": 0.7,
        "ARTIFACT.MIXED_STATE_MARGIN": 0.1,
    }
    report = run_shadow_mode(records, parameters)
    row = report["records"][0]
    assert row["canonical_state"] == "AMBIGUOUS"
    assert row["change_class"] == "CANONICAL_MORE_CONSERVATIVE"
    assert row["production_activated"] is False


def test_shadow_mode_one_label_cannot_become_exact_identity() -> None:
    records = [
        {
            "source_id": "locator-001",
            "kind": "locator",
            "baseline_state": "EXACT",
            "observation": {
                "candidates": [
                    {
                        "candidate_id": "duplicate-road-name",
                        "text_score": 1.0,
                        "road_score": 0.95,
                        "hydro_score": 0.95,
                        "terrain_score": 0.95,
                        "building_score": 0.95,
                        "landmark_score": 0.95,
                        "vegetation_score": 0.95,
                        "multiframe_score": 0.95,
                        "generic_similarity_score": 0.95,
                        "text_cue_count": 1,
                        "independent_topology_support": False,
                    }
                ]
            },
        }
    ]
    parameters = {
        "LOCATOR.TEXT_WEIGHT": 0.2,
        "LOCATOR.ROAD_GRAPH_WEIGHT": 0.2,
        "LOCATOR.HYDROGRAPHY_WEIGHT": 0.2,
        "LOCATOR.TERRAIN_WEIGHT": 0.1,
        "LOCATOR.BUILDING_WEIGHT": 0.1,
        "LOCATOR.LANDMARK_WEIGHT": 0.1,
        "LOCATOR.VEGETATION_WEIGHT": 0.02,
        "LOCATOR.MULTIFRAME_WEIGHT": 0.05,
        "LOCATOR.GENERIC_SIMILARITY_WEIGHT": 0.03,
        "LOCATOR.HARD_CONTRADICTION_PENALTY": 1.0,
        "LOCATOR.SOFT_CONTRADICTION_PENALTY": 0.05,
        "LOCATOR.MIN_CANDIDATES_PRESERVED": 1.0,
        "LOCATOR.MAX_CANDIDATES_PRESERVED": 5.0,
        "LOCATOR.RUNNER_UP_MARGIN_MIN": 0.08,
        "LOCATOR.L1_THRESHOLD": 0.2,
        "LOCATOR.L2_THRESHOLD": 0.35,
        "LOCATOR.L3_THRESHOLD": 0.5,
        "LOCATOR.L4_THRESHOLD": 0.62,
        "LOCATOR.L5_THRESHOLD": 0.72,
        "LOCATOR.L6_THRESHOLD": 0.82,
        "LOCATOR.L7_THRESHOLD": 0.92,
    }
    report = run_shadow_mode(records, parameters)
    row = report["records"][0]
    assert row["canonical_state"] == "MULTIPLE_CANDIDATES"
    assert "RC_ONE_LABEL_NOT_EXACT" in row["reason_codes"]
    assert row["production_activated"] is False
