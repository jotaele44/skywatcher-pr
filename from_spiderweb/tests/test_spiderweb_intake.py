"""Tests for spiderweb_intake.py: normalization, dedup, scoring, gap audit."""

import csv
import json
from pathlib import Path

import pytest

from readiness.spiderweb_intake import (
    BRIDGE_FILES,
    DEDUP_THRESH_DEG,
    REQUIRED_FIELDS,
    SpiderwebIntake,
)


# ── Fixture helpers ───────────────────────────────────────────────────────────

CRS = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4326"}}

def _write_poi(tmp_path: Path, features=None) -> None:
    if features is None:
        features = [_poi_feature(18.35, -66.32)]
    fc = {"type": "FeatureCollection", "crs": CRS, "features": features}
    (tmp_path / "airspace_poi_candidates.geojson").write_text(json.dumps(fc))


def _write_ilap(tmp_path: Path, features=None) -> None:
    if features is None:
        features = [_ilap_feature("FLT_001", "N5854Z", 0.7)]
    fc = {"type": "FeatureCollection", "crs": CRS, "features": features}
    (tmp_path / "airspace_ilap_candidates.geojson").write_text(json.dumps(fc))


def _write_corridor(tmp_path: Path, features=None) -> None:
    if features is None:
        features = [_corridor_feature(18.35, -66.32, 18.45, -66.10, 3)]
    fc = {"type": "FeatureCollection", "crs": CRS, "features": features}
    (tmp_path / "airspace_corridor_candidates.geojson").write_text(json.dumps(fc))


def _write_edges(tmp_path: Path, rows=None) -> None:
    if rows is None:
        rows = [_edge_row()]
    fieldnames = [
        "edge_id", "from_node", "to_node",
        "from_lat", "from_lon", "to_lat", "to_lon",
        "weight", "flight_count", "avg_duration_min",
        "dominant_callsign", "confidence_score",
    ]
    with open(tmp_path / "aasb_airspace_edges.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _write_manifest(tmp_path: Path) -> None:
    manifest = {
        "generated_at": "2024-01-01T00:00:00Z",
        "schema_version": "1.0",
        "files": [],
    }
    (tmp_path / "spiderweb_ingest_manifest.json").write_text(json.dumps(manifest))


def _write_all_five(tmp_path: Path) -> None:
    _write_poi(tmp_path)
    _write_ilap(tmp_path)
    _write_corridor(tmp_path)
    _write_edges(tmp_path)
    _write_manifest(tmp_path)


def _poi_feature(lat, lon, confidence=0.5):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "lat": lat, "lon": lon,
            "overall_confidence": confidence,
            "review_priority": "MEDIUM",
            "identity_note": "not standalone evidence",
        },
    }


def _ilap_feature(flight_id, callsign, corridor_score):
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[-66.0, 18.4], [-66.5, 18.1]],
        },
        "properties": {
            "flight_id": flight_id,
            "callsign": callsign,
            "corridor_alignment_score": corridor_score,
            "mission_type": "patrol",
            "identity_note": "not standalone evidence",
        },
    }


def _corridor_feature(lat1, lon1, lat2, lon2, connecting_flights=3):
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[lon1, lat1], [lon2, lat2]],
        },
        "properties": {
            "poi_a": f"{lat1},{lon1}",
            "poi_b": f"{lat2},{lon2}",
            "connecting_flights": connecting_flights,
            "identity_note": "not standalone evidence",
        },
    }


def _edge_row(edge_id="EDGE_0000_SJU_PSE", from_node="SJU", to_node="PSE",
              from_lat=18.4373, from_lon=-66.0018,
              to_lat=18.0083, to_lon=-66.5632,
              weight=5, flight_count=5, avg_duration_min=45.0,
              dominant_callsign="N5854Z", confidence_score=1.0):
    return {
        "edge_id": edge_id,
        "from_node": from_node, "to_node": to_node,
        "from_lat": from_lat, "from_lon": from_lon,
        "to_lat": to_lat, "to_lon": to_lon,
        "weight": weight, "flight_count": flight_count,
        "avg_duration_min": avg_duration_min,
        "dominant_callsign": dominant_callsign,
        "confidence_score": confidence_score,
    }


# ── Phase A: intake runs cleanly ──────────────────────────────────────────────

def test_intake_runs_on_empty_dir(tmp_path):
    result = SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    assert "gap_audit" in result
    assert result["total_candidates"] == 0
    assert len(result["gap_audit"]["gaps"]["export_gap"]["missing_files"]) == len(BRIDGE_FILES)


def test_intake_runs_on_full_five_file_set(tmp_path):
    _write_all_five(tmp_path)
    result = SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    assert result["total_candidates"] > 0
    assert result["gap_audit"]["gaps"]["export_gap"]["missing_files"] == []


# ── Phase B: candidate loading and normalization ──────────────────────────────

def test_intake_loads_poi_candidates(tmp_path):
    _write_poi(tmp_path)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    pois = [f for f in data["features"] if f["properties"]["candidate_type"] == "poi"]
    assert len(pois) == 1
    assert pois[0]["properties"]["source_layer"] == "airspace_spiderweb_export"


def test_overlay_features_carry_meta_block(tmp_path):
    """T5-41: every spiderweb overlay Feature must carry a _meta block."""
    _write_poi(tmp_path)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    assert data["features"], "expected at least one feature"
    for feat in data["features"]:
        meta = feat["properties"].get("_meta")
        assert meta is not None, "missing _meta block"
        assert meta["producer_module"] == "readiness.spiderweb_intake"
        assert meta["source_artifact"] == "spiderweb_overlay_candidates.geojson"
        assert meta["produced_at"], "produced_at must be non-empty"


def test_intake_loads_ilap_candidates(tmp_path):
    _write_ilap(tmp_path)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    ilaps = [f for f in data["features"] if f["properties"]["candidate_type"] == "ilap"]
    assert len(ilaps) == 1
    assert ilaps[0]["properties"]["linked_flight_id"] == "FLT_001"


def test_intake_loads_corridor_candidates(tmp_path):
    _write_corridor(tmp_path)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    corridors = [f for f in data["features"] if f["properties"]["candidate_type"] == "corridor"]
    assert len(corridors) == 1
    assert corridors[0]["properties"]["corridor_id"] is not None


def test_intake_loads_aasb_edges(tmp_path):
    _write_edges(tmp_path)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    edges = [f for f in data["features"] if f["properties"]["candidate_type"] == "aasb_edge"]
    assert len(edges) == 1
    assert edges[0]["properties"]["corridor_id"] == "EDGE_0000_SJU_PSE"


# ── Dedup ─────────────────────────────────────────────────────────────────────

def test_dedup_removes_near_duplicates(tmp_path):
    # Two POIs within DEDUP_THRESH_DEG → only 1 kept
    feats = [
        _poi_feature(18.35, -66.32),
        _poi_feature(18.35 + DEDUP_THRESH_DEG * 0.5, -66.32 + DEDUP_THRESH_DEG * 0.5),
    ]
    _write_poi(tmp_path, features=feats)
    result = SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    assert result["gap_audit"]["gaps"]["dedup_gap"]["duplicates_removed"] == 1
    assert result["total_candidates"] == 1


def test_dedup_keeps_distant_candidates(tmp_path):
    feats = [_poi_feature(18.35, -66.32), _poi_feature(18.45, -66.10)]
    _write_poi(tmp_path, features=feats)
    result = SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    assert result["total_candidates"] == 2
    assert result["gap_audit"]["gaps"]["dedup_gap"]["duplicates_removed"] == 0


# ── Evidence tier and review status ──────────────────────────────────────────

def test_evidence_tier_t1_requires_two_corroborating_signals(tmp_path):
    # Lago La Plata coords + utility corridor → hydro=yes, utility=yes; confidence≥0.65 → T1
    feats = [_poi_feature(18.3517, -66.3200, confidence=0.80)]
    _write_poi(tmp_path, features=feats)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    props = data["features"][0]["properties"]
    assert props["evidence_tier"] == "T1"
    assert props["review_status"] == "accepted"


def test_evidence_tier_t4_for_low_confidence_no_signals(tmp_path):
    # Far from everything, low confidence → T4, rejected
    feats = [_poi_feature(17.95, -65.55, confidence=0.10)]
    _write_poi(tmp_path, features=feats)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    props = data["features"][0]["properties"]
    assert props["evidence_tier"] == "T4"
    assert props["review_status"] == "rejected"


def test_review_status_manual_for_t3(tmp_path):
    # Corridor with ≥2 connecting flights but no high confidence → T3, manual_review
    feats = [_corridor_feature(17.98, -65.62, 18.05, -65.70, connecting_flights=2)]
    _write_corridor(tmp_path, features=feats)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    props = data["features"][0]["properties"]
    assert props["evidence_tier"] == "T3"
    assert props["review_status"] == "manual_review"


# ── Hydro scoring ─────────────────────────────────────────────────────────────

def test_hydro_overlap_near_lago_la_plata(tmp_path):
    feats = [_poi_feature(18.3517, -66.3200)]
    _write_poi(tmp_path, features=feats)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    assert data["features"][0]["properties"]["hydro_overlap"] == "yes"


# ── MBIL scoring ──────────────────────────────────────────────────────────────

def test_mbil_class_near_san_juan(tmp_path):
    feats = [_poi_feature(18.4655, -66.1057)]
    _write_poi(tmp_path, features=feats)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    assert data["features"][0]["properties"]["mbil_class"] == "MBIL-3"


def test_mbil_class_remote_location(tmp_path):
    feats = [_poi_feature(17.92, -65.52)]  # far from all centroids
    _write_poi(tmp_path, features=feats)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    assert data["features"][0]["properties"]["mbil_class"] == "MBIL-0"


# ── Terrain scoring ───────────────────────────────────────────────────────────

def test_terrain_coastal_west(tmp_path):
    feats = [_poi_feature(18.49, -67.35)]  # beyond PR_LON_WEST
    _write_poi(tmp_path, features=feats)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    assert data["features"][0]["properties"]["terrain_context"] == "coastal"


def test_terrain_urban_sju(tmp_path):
    feats = [_poi_feature(18.42, -66.06)]
    _write_poi(tmp_path, features=feats)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    assert data["features"][0]["properties"]["terrain_context"] == "urban"


# ── Output files ──────────────────────────────────────────────────────────────

def test_overlay_geojson_created(tmp_path):
    _write_all_five(tmp_path)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    overlay_path = tmp_path / "spiderweb_overlay_candidates.geojson"
    assert overlay_path.exists()
    data = json.loads(overlay_path.read_text())
    assert data["type"] == "FeatureCollection"
    assert "4326" in data["crs"]["properties"]["name"]


def test_gap_audit_json_created(tmp_path):
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    audit_path = tmp_path / "spiderweb_gap_audit.json"
    assert audit_path.exists()
    audit = json.loads(audit_path.read_text())
    expected_gaps = {"export_gap", "dedup_gap", "spatial_gap", "evidence_gap", "temporal_gap", "mbil_gap"}
    assert set(audit["gaps"].keys()) == expected_gaps


def test_export_gap_detects_missing_file(tmp_path):
    # Only write 4 of 5 files (no manifest)
    _write_poi(tmp_path)
    _write_ilap(tmp_path)
    _write_corridor(tmp_path)
    _write_edges(tmp_path)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    audit = json.loads((tmp_path / "spiderweb_gap_audit.json").read_text())
    assert "spiderweb_ingest_manifest.json" in audit["gaps"]["export_gap"]["missing_files"]


def test_all_required_fields_present(tmp_path):
    _write_all_five(tmp_path)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    for feat in data["features"]:
        for field in REQUIRED_FIELDS:
            assert field in feat["properties"], f"Missing field: {field}"


# ── Operational calibration: expanded scoring constants ───────────────────────

def test_ponce_metro_urban(tmp_path):
    feats = [_poi_feature(18.01, -66.60)]
    _write_poi(tmp_path, features=feats)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    assert data["features"][0]["properties"]["terrain_context"] == "urban"


def test_mayaguez_metro_urban(tmp_path):
    feats = [_poi_feature(18.22, -67.14)]
    _write_poi(tmp_path, features=feats)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    assert data["features"][0]["properties"]["terrain_context"] == "urban"


def test_lago_carraizo_hydro(tmp_path):
    feats = [_poi_feature(18.33, -65.97)]
    _write_poi(tmp_path, features=feats)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    assert data["features"][0]["properties"]["hydro_overlap"] == "yes"


def test_lago_guajataca_hydro(tmp_path):
    feats = [_poi_feature(18.43, -66.85)]
    _write_poi(tmp_path, features=feats)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    assert data["features"][0]["properties"]["hydro_overlap"] == "yes"


def test_aguadilla_mbil3(tmp_path):
    feats = [_poi_feature(18.49, -67.14)]
    _write_poi(tmp_path, features=feats)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    assert data["features"][0]["properties"]["mbil_class"] == "MBIL-3"


def test_caguas_mbil3(tmp_path):
    feats = [_poi_feature(18.28, -65.90)]
    _write_poi(tmp_path, features=feats)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    assert data["features"][0]["properties"]["mbil_class"] == "MBIL-3"


def test_off_island_gets_mbil_x(tmp_path):
    """Off-island candidates (here: north Atlantic at lat=20.0) get MBIL-X
    rather than MBIL-0. MBIL-0 means 'scored, no signal'; MBIL-X means
    'unclassified' — distinct semantics per docs/SPIDERWEB_LANGUAGE_BRIDGE.md."""
    feats = [_poi_feature(20.0, -66.0)]  # north Atlantic, outside PR lat bounds
    _write_poi(tmp_path, features=feats)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    data = json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())
    assert data["features"][0]["properties"]["mbil_class"] == "MBIL-X"


def test_calibration_driver_report_structure(tmp_path):
    from readiness.calibrate_scoring import REQUIRED_REPORT_KEYS, CalibrationDriver

    _write_all_five(tmp_path)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    report = CalibrationDriver(str(tmp_path)).run()

    report_path = tmp_path / "calibration_report.json"
    assert report_path.exists()
    loaded = json.loads(report_path.read_text())
    for key in REQUIRED_REPORT_KEYS:
        assert key in loaded, f"Missing key in calibration report: {key}"
    assert loaded["baseline_mode"] in ("fixture", "operational")
    assert loaded["status"] in ("PASS", "WARN", "FAIL")
    assert isinstance(loaded["missing_inputs"], list)


# ── Calibration hardening tests ───────────────────────────────────────────────

def _write_overlay_geojson(tmp_path, n_t4=0, n_t1=0):
    features = []
    for i in range(n_t4):
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-66.0 - i * 0.01, 18.4]},
            "properties": {
                "candidate_type": "ilap", "evidence_tier": "T4",
                "mbil_class": "MBIL-0", "hydro_overlap": "no",
                "utility_overlap": "no", "terrain_context": "inland",
                "review_status": "rejected",
                "lat": 18.4, "lon": -66.0 - i * 0.01,
            },
        })
    for i in range(n_t1):
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-66.5, 18.2]},
            "properties": {
                "candidate_type": "poi", "evidence_tier": "T1",
                "mbil_class": "MBIL-3", "hydro_overlap": "yes",
                "utility_overlap": "yes", "terrain_context": "urban",
                "review_status": "accepted",
                "lat": 18.2, "lon": -66.5,
            },
        })
    fc = {"type": "FeatureCollection", "features": features}
    (tmp_path / "spiderweb_overlay_candidates.geojson").write_text(json.dumps(fc))


def _write_gap_audit_json(tmp_path, dups_removed=0):
    audit = {
        "total_candidates": 0, "after_dedup": 0,
        "gaps": {
            "dedup_gap": {"duplicates_removed": dups_removed, "threshold_deg": 0.00045},
            "export_gap": {"missing_files": []},
        },
    }
    (tmp_path / "spiderweb_gap_audit.json").write_text(json.dumps(audit))


def test_calibration_missing_overlay_reports_missing_inputs(tmp_path):
    from readiness.calibrate_scoring import CalibrationDriver
    report = CalibrationDriver(str(tmp_path)).run()
    assert "spiderweb_overlay_candidates.geojson" in report["missing_inputs"]
    assert report["candidate_count"] == 0
    assert report["status"] == "PASS"


def test_calibration_empty_overlay_no_crash(tmp_path):
    from readiness.calibrate_scoring import CalibrationDriver
    _write_overlay_geojson(tmp_path, n_t4=0)
    _write_gap_audit_json(tmp_path)
    report = CalibrationDriver(str(tmp_path)).run()
    assert report["candidate_count"] == 0
    assert report["status"] == "PASS"


def test_calibration_fixture_mode_no_fail_on_all_t4(tmp_path):
    from readiness.calibrate_scoring import CalibrationDriver, MIN_OPERATIONAL_CANDIDATES
    _write_overlay_geojson(tmp_path, n_t4=MIN_OPERATIONAL_CANDIDATES - 1)
    _write_gap_audit_json(tmp_path)
    report = CalibrationDriver(str(tmp_path)).run()
    assert report["baseline_mode"] == "fixture"
    assert report["status"] == "WARN"
    flag_metrics = [f["metric"] for f in report["calibration_flags"]]
    assert "pct_T4" not in flag_metrics


def test_calibration_operational_mode_fails_on_all_t4(tmp_path):
    from readiness.calibrate_scoring import CalibrationDriver, MIN_OPERATIONAL_CANDIDATES
    _write_overlay_geojson(tmp_path, n_t4=MIN_OPERATIONAL_CANDIDATES)
    _write_gap_audit_json(tmp_path)
    report = CalibrationDriver(str(tmp_path)).run()
    assert report["baseline_mode"] == "operational"
    assert report["status"] == "FAIL"
    flag_metrics = [f["metric"] for f in report["calibration_flags"]]
    assert "pct_T4" in flag_metrics


def test_calibration_flags_sorted_by_metric(tmp_path):
    from readiness.calibrate_scoring import CalibrationDriver, MIN_OPERATIONAL_CANDIDATES
    _write_overlay_geojson(tmp_path, n_t4=MIN_OPERATIONAL_CANDIDATES)
    _write_gap_audit_json(tmp_path)
    report = CalibrationDriver(str(tmp_path)).run()
    metrics = [f["metric"] for f in report["calibration_flags"]]
    assert metrics == sorted(metrics)


def test_overlay_output_is_deterministic(tmp_path):
    _write_all_five(tmp_path)
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    coords_first = [
        f["geometry"]["coordinates"]
        for f in json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())["features"]
    ]
    SpiderwebIntake(str(tmp_path), str(tmp_path)).run()
    coords_second = [
        f["geometry"]["coordinates"]
        for f in json.loads((tmp_path / "spiderweb_overlay_candidates.geojson").read_text())["features"]
    ]
    assert coords_first == coords_second


def test_empty_intake_dir_produces_report(tmp_path):
    intake = SpiderwebIntake(str(tmp_path / "in"), str(tmp_path / "out"))
    report = intake.run()
    assert isinstance(report, dict)
    assert "missing_files" in report or "candidate_count" in report or report is not None


# ── Phase 7: SpiderwebIntake hardening methods ────────────────────────────────

def test_get_candidate_summary_empty():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    summary = intake.get_candidate_summary([])
    assert summary["total"] == 0
    assert summary["by_type"] == {}
    assert summary["by_tier"] == {}


def test_get_candidate_summary_counts_types():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    candidates = [
        {"_candidate_type": "poi", "_lat": 18.0, "_lon": -66.0},
        {"_candidate_type": "poi", "_lat": 18.1, "_lon": -66.1},
        {"_candidate_type": "ilap", "_lat": 18.2, "_lon": -66.2},
    ]
    summary = intake.get_candidate_summary(candidates)
    assert summary["total"] == 3
    assert summary["by_type"]["poi"] == 2
    assert summary["by_type"]["ilap"] == 1


def test_filter_by_tier_returns_matching():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    candidates = [
        {"_candidate_type": "poi", "evidence_tier": "TIER-1"},
        {"_candidate_type": "poi", "evidence_tier": "TIER-2"},
        {"_candidate_type": "ilap", "evidence_tier": "TIER-1"},
    ]
    t1 = intake.filter_by_tier(candidates, "TIER-1")
    assert len(t1) == 2
    assert all(c["evidence_tier"] == "TIER-1" for c in t1)


def test_filter_by_tier_empty_on_no_match():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    candidates = [{"evidence_tier": "TIER-2"}]
    assert intake.filter_by_tier(candidates, "TIER-1") == []


def test_validate_candidate_fields_valid():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    candidate = {"_lat": 18.0, "_lon": -66.0, "_candidate_type": "poi"}
    assert intake.validate_candidate_fields(candidate) == []


def test_validate_candidate_fields_missing_field():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    candidate = {"_lat": 18.0, "_lon": -66.0}  # missing _candidate_type
    errors = intake.validate_candidate_fields(candidate)
    assert len(errors) >= 1
    assert any("_candidate_type" in e for e in errors)


def test_validate_candidate_fields_none_lat():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    candidate = {"_lat": None, "_lon": -66.0, "_candidate_type": "poi"}
    errors = intake.validate_candidate_fields(candidate)
    assert any("_lat" in e for e in errors)


# ── Phase 10: Observability ───────────────────────────────────────────────────

def test_get_coverage_stats_returns_bbox():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    candidates = [
        {"_lat": 18.1, "_lon": -66.5, "_candidate_type": "A"},
        {"_lat": 18.3, "_lon": -66.2, "_candidate_type": "A"},
        {"_lat": 18.0, "_lon": -66.8, "_candidate_type": "B"},
    ]
    stats = intake.get_coverage_stats(candidates)
    assert stats["total_with_coords"] == 3
    assert abs(stats["bbox"][1] - 18.0) < 1e-5
    assert abs(stats["bbox"][3] - 18.3) < 1e-5


def test_get_coverage_stats_empty_returns_nones():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    stats = intake.get_coverage_stats([])
    assert stats["total_with_coords"] == 0
    assert stats["bbox"] == [None, None, None, None]


def test_get_coverage_stats_skips_none_coords():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    candidates = [
        {"_lat": None, "_lon": -66.5, "_candidate_type": "A"},
        {"_lat": 18.2, "_lon": -66.3, "_candidate_type": "B"},
    ]
    stats = intake.get_coverage_stats(candidates)
    assert stats["total_with_coords"] == 1


def test_get_coverage_stats_lon_range():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    candidates = [
        {"_lat": 18.0, "_lon": -67.0, "_candidate_type": "A"},
        {"_lat": 18.0, "_lon": -65.5, "_candidate_type": "A"},
    ]
    stats = intake.get_coverage_stats(candidates)
    assert abs(stats["lon_range"][0] - (-67.0)) < 1e-5
    assert abs(stats["lon_range"][1] - (-65.5)) < 1e-5


# ── Tier 3 additive fields (D5) ──────────────────────────────────────────────


def _baseline_candidate(**overrides):
    """A minimal candidate dict ready for any single _score_* helper."""
    base = {
        "_raw_props": {},
        "candidate_type": "poi",
        "lat": 18.4373, "lon": -66.0018,   # SJU airport, in MUNICIPAL_CENTROIDS
        "confidence": 0.50,
        "evidence_tier": None,
        "linked_flight_id": None, "linked_aircraft": None, "corridor_id": None,
        "mbil_class": "MBIL-0",
        "hydro_overlap": "no", "utility_overlap": "no", "terrain_context": "flat",
        "review_status": "unreviewed",
    }
    base.update(overrides)
    return base


def test_score_spiderweb_role_maps_each_candidate_type():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    cands = [_baseline_candidate(candidate_type=ct) for ct in
             ("poi", "ilap", "corridor", "aasb_edge", "unknown")]
    intake._score_spiderweb_role(cands)
    assert [c["spiderweb_role"] for c in cands] == [
        "node", "path", "edge", "airport_link", "node",
    ]


def test_score_access_assertion_public_record_for_airport_anchored():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    cands = [
        _baseline_candidate(candidate_type="aasb_edge"),
        _baseline_candidate(candidate_type="corridor", corridor_id="SJU_BQN_corridor"),
        _baseline_candidate(candidate_type="poi", corridor_id="random_island_road"),
        _baseline_candidate(candidate_type="poi", corridor_id=None),
    ]
    intake._score_access_assertion(cands)
    assert [c["access_assertion_level"] for c in cands] == [
        "public_record", "public_record", "derived_observation", "derived_observation",
    ]


def test_nearest_municipal_boundary_at_sju_is_zero():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    # SJU centroid is in MUNICIPAL_CENTROIDS; distance to itself ≈ 0.
    cands = [_baseline_candidate(lat=18.4655, lon=-66.1057)]  # San Juan
    intake._score_nearest_municipal_boundary_m(cands)
    assert cands[0]["nearest_municipal_boundary_m"] == 0.0


def test_nearest_municipal_boundary_at_ocean_is_large():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    # Mid-Atlantic point — well off PR.
    cands = [_baseline_candidate(lat=20.0, lon=-50.0)]
    intake._score_nearest_municipal_boundary_m(cands)
    # Should be in the thousands of km; just assert > 1,000,000 m.
    assert cands[0]["nearest_municipal_boundary_m"] > 1_000_000


def test_aasb_mbil_corridor_flag_only_fires_on_corridor_with_mbil_high():
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    cands = [
        _baseline_candidate(candidate_type="corridor", mbil_class="MBIL-3"),
        _baseline_candidate(candidate_type="corridor", mbil_class="MBIL-2"),
        _baseline_candidate(candidate_type="corridor", mbil_class="MBIL-1"),
        _baseline_candidate(candidate_type="poi",      mbil_class="MBIL-3"),
    ]
    intake._score_aasb_mbil_corridor_flag(cands)
    assert [c["aasb_mbil_corridor_flag"] for c in cands] == [True, True, False, False]


def test_fact_status_observed_requires_two_non_mbil_corroborating():
    """fact_status='observed' needs high confidence AND ≥2 non-MBIL corroborating
    signals. MBIL alone never counts toward the observed gate."""
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    cands = [
        # High confidence + 2 non-MBIL (hydro + utility) → observed
        _baseline_candidate(confidence=0.80, hydro_overlap="yes", utility_overlap="yes"),
        # High confidence + only MBIL — inferred (guardrail)
        _baseline_candidate(confidence=0.95, mbil_class="MBIL-3"),
        # Low confidence + 2 non-MBIL — inferred (confidence gate failed)
        _baseline_candidate(confidence=0.30, hydro_overlap="yes", utility_overlap="yes"),
    ]
    intake._assign_evidence_tier(cands)
    assert [c["fact_status"] for c in cands] == ["observed", "inferred", "inferred"]


def test_mbil_only_guardrail_caps_tier_at_t3():
    """T3-27: a MBIL-3 candidate with no hydro/utility/corridor MUST cap at T3,
    even at very high confidence."""
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    cands = [_baseline_candidate(
        confidence=0.99, mbil_class="MBIL-3",
        hydro_overlap="no", utility_overlap="no", corridor_id=None,
    )]
    intake._assign_evidence_tier(cands)
    assert cands[0]["evidence_tier"] in ("T3", "T4")
    assert cands[0]["evidence_tier"] != "T1"
    assert cands[0]["evidence_tier"] != "T2"


def test_mbil_does_not_block_genuine_t1():
    """Sanity: when non-MBIL corroborating is present, MBIL can still co-exist
    at T1 (the guardrail only blocks MBIL-ALONE escalation)."""
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    cands = [_baseline_candidate(
        confidence=0.90,
        hydro_overlap="yes", utility_overlap="yes",  # 2 non-MBIL
        mbil_class="MBIL-3",                          # MBIL on top — fine
    )]
    intake._assign_evidence_tier(cands)
    assert cands[0]["evidence_tier"] == "T1"
    assert cands[0]["fact_status"] == "observed"


# ── T3-25 — MBIL-X (unclassified) ────────────────────────────────────────────


def test_mbil_x_for_off_island_candidate():
    """A candidate clearly outside PR bounds gets MBIL-X, not a numeric tier."""
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    cands = [{"_lat": 20.0, "_lon": -50.0}]  # Mid-Atlantic
    intake._score_mbil(cands)
    assert cands[0]["mbil_class"] == "MBIL-X"


def test_mbil_x_for_missing_coordinates():
    """Null lat/lon → MBIL-X (geometry not scoreable)."""
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    cands = [
        {"_lat": None, "_lon": -66.0},
        {"_lat": 18.4, "_lon": None},
        {"_lat": None, "_lon": None},
    ]
    intake._score_mbil(cands)
    assert all(c["mbil_class"] == "MBIL-X" for c in cands)


def test_mbil_x_for_on_island_still_gets_numeric_tier():
    """Off-island guard isn't too aggressive — SJU still scores MBIL-3."""
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    cands = [{"_lat": 18.4373, "_lon": -66.0018}]  # SJU airport
    intake._score_mbil(cands)
    assert cands[0]["mbil_class"] == "MBIL-3"


def test_mbil_x_does_not_count_as_corroborating():
    """MBIL-X is 'unknown' — must NOT count toward the corroboration score.
    A candidate with high confidence + MBIL-X but no other signals stays
    below T1 (only MBIL-1/2/3 contribute to corroboration)."""
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    cands = [_baseline_candidate(
        confidence=0.99, mbil_class="MBIL-X",
        hydro_overlap="no", utility_overlap="no", corridor_id=None,
    )]
    intake._assign_evidence_tier(cands)
    assert cands[0]["evidence_tier"] != "T1"


def test_mbil_x_not_flagged_as_aasb_mbil_corridor():
    """A corridor candidate with MBIL-X must NOT trigger aasb_mbil_corridor_flag."""
    intake = SpiderwebIntake("/tmp/in", "/tmp/out")
    cands = [_baseline_candidate(candidate_type="corridor", mbil_class="MBIL-X")]
    intake._score_aasb_mbil_corridor_flag(cands)
    assert cands[0]["aasb_mbil_corridor_flag"] is False
