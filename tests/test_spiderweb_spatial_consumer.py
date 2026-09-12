import hashlib
import json

import pytest

from skywatcher.spatial_context import SpatialArtifactError, compare_track_contexts, consume_result_set, consume_spiderweb_result, derive_spatial_events, spiderweb_handoff_url


def artifact(**changes):
    payload = {"contract_version": "spatial-analysis-result/1.0", "producer_repo": "spiderweb-pr", "analysis_id": "a1", "query_id": "q1", "subject_type": "flight_track", "subject_id": "track-1", "subject_manifestation_id": "track-snapshot-1", "geometry_role": "TRACK_POSITION_UNCERTAINTY", "input_geometry_hash": "a" * 64, "input_time_start": None, "input_time_end": None, "target_domain": "OCEAN_DEPTH", "target_feature_id": None, "target_candidate_id": "ridge-1", "spatial_state": "PARTIAL", "identity_state": "CANDIDATE_NOT_IDENTITY", "source_manifestation_ids": ["gebco-pr-2023"], "measurement_classes": ["INTERPOLATED"], "resolution_summary": {"best_m": 463.0, "worst_m": 463.0, "dominant_m": 463.0, "direct_coverage_fraction": 0, "interpolated_fraction": 1, "nodata_fraction": 0}, "distance_m": None, "intersection_length_m": 1200.0, "intersection_area_m2": None, "surface_depth_min_m": -800.0, "surface_depth_max_m": -500.0, "surface_depth_mean_m": -650.0, "slope_max_deg": 12.0, "local_relief_m": 300.0, "analysis_engine_version": "surface/1.0", "crs_operation": "EPSG:4326->EPSG:32620", "horizontal_source_crs": "EPSG:4326", "horizontal_computation_crs": "EPSG:32620", "vertical_datum": "mean_sea_level_assumed", "depth_sign_convention": "positive_up", "units": "metres", "confidence_state": "LOW", "analysis_timestamp_utc": "2026-09-08T20:00:00+00:00"}
    payload.update(changes)
    payload["result_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return payload


def test_consumes_intact_spiderweb_artifact_without_geometry_logic():
    context = consume_spiderweb_result(artifact())
    assert context.spatial_state == "PARTIAL"
    assert context.identity_state == "CANDIDATE_NOT_IDENTITY"


def test_rejects_non_spiderweb_geometry_authority():
    with pytest.raises(SpatialArtifactError, match="Spiderweb-authoritative"):
        consume_spiderweb_result(artifact(producer_repo="skywatcher-pr"))


def test_rejects_tampering_and_candidate_promotion():
    tampered = artifact()
    tampered["surface_depth_mean_m"] = 0
    with pytest.raises(SpatialArtifactError, match="hash mismatch"):
        consume_spiderweb_result(tampered)
    with pytest.raises(SpatialArtifactError, match="promoted"):
        consume_spiderweb_result(artifact(identity_state="AUTHORITATIVE_BINDING"))


def test_rejects_nodata_as_zero_and_unknown_vertical_datum():
    with pytest.raises(SpatialArtifactError, match="NULL_EMPTY"):
        consume_spiderweb_result(artifact(spatial_state="NULL_EMPTY", surface_depth_min_m=0, surface_depth_max_m=None, surface_depth_mean_m=None))
    with pytest.raises(SpatialArtifactError, match="vertical datum"):
        consume_spiderweb_result(artifact(vertical_datum=None))


def test_result_set_rejects_duplicate_whole_records():
    item = artifact()
    with pytest.raises(SpatialArtifactError, match="duplicate"):
        consume_result_set([item, item])


def test_derived_events_remain_distinct_from_aircraft_observations():
    context = consume_spiderweb_result(artifact(target_domain="SHELF_BREAK"))
    event = derive_spatial_events([context])[0]
    assert event["event_type"] == "CROSSED_SHELF_BREAK"
    assert event["event_class"] == "DERIVED_SPATIAL_EVENT"
    assert event["aircraft_source_observation"] is False


def test_track_comparison_returns_complete_set_algebra():
    a = [consume_spiderweb_result(artifact(analysis_id="a1", target_candidate_id="ridge-1"))]
    b = [consume_spiderweb_result(artifact(analysis_id="b1", target_candidate_id="ridge-2"))]
    result = compare_track_contexts(a, b)
    assert result["INTERSECTION"] == ()
    assert result["A_ONLY"] == ("candidate:ridge-1",)
    assert result["B_ONLY"] == ("candidate:ridge-2",)
    assert result["UNION"] == ("candidate:ridge-1", "candidate:ridge-2")
    assert result["SYMMETRIC_DIFFERENCE"] == result["UNION"]


def test_handoff_binds_analysis_and_result_hash():
    context = consume_spiderweb_result(artifact())
    url = spiderweb_handoff_url("https://spiderweb.example", context, time_start="2026-09-08T00:00Z")
    assert "/spatial-workbench?" in url
    assert "analysis_id=a1" in url and context.result_hash in url
