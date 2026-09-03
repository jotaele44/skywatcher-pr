"""Read-only API projection of persisted RLSM aircraft spatial truth."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from server.backend import main as backend

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "data" / "rlsm" / "schema.sql"
NOW = "2026-08-01T00:00:00Z"


def _fixture_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute(
        """INSERT INTO screenshots
           (screenshot_id, sha256, filename, rel_path, filename_ts, ext,
            size_bytes, width, height, ingest_status, ingested_at)
           VALUES (1, ?, 'frame.png', 'images/frame.png', ?, '.png', 1,
                   200, 400, 'ok', ?)""",
        ("1" * 64, NOW, NOW),
    )
    conn.execute(
        """INSERT INTO aircraft_observations
           (aircraft_obs_id, screenshot_id, registration, callsign, aircraft_type,
            altitude_ft, speed_kt, heading_deg, operator_text, confidence,
            pixel_x, pixel_y, icon_rotation_deg, marker_confidence, marker_method,
            position_lat, position_lon, position_method, position_confidence,
            position_error_m, position_observed_at, observed_at)
           VALUES (1, 1, 'N123AB', 'TEST1', 'B407', 2500, 110, 137,
                   'Fixture Operator', 0.95, 100, 120, 42, 0.94,
                   'rlsm-aircraft-marker-v1', 18.21, -66.49,
                   'multi_anchor_affine', 0.90, 120, ?, ?)""",
        (NOW, NOW),
    )
    conn.execute(
        """INSERT INTO aircraft_marker_frames
           (screenshot_id, detector_version, status, candidate_count,
            selected_candidate_rank, viewport_x, viewport_y, viewport_w,
            viewport_h, reason, observed_at)
           VALUES (1, 'rlsm-aircraft-marker-v1', 'selected', 1, 1,
                   0, 20, 200, 240, 'fixture', ?)""",
        (NOW,),
    )
    conn.execute(
        """INSERT INTO aircraft_marker_detections
           (marker_frame_id, screenshot_id, aircraft_obs_id, candidate_rank,
            selected, bbox_x, bbox_y, bbox_w, bbox_h, centroid_x, centroid_y,
            rotation_deg, rotation_status, area_px, hue_deg, saturation, value,
            fill_ratio, axis_ratio, direction_asymmetry, silhouette_hash,
            confidence, features_json, observed_at)
           VALUES (1, 1, 1, 1, 1, 90, 105, 20, 30, 100, 120, 42,
                   'resolved', 200, 340, 0.9, 0.9, 0.33, 2.1, 0.25,
                   'fixture-hash', 0.94, '{}', ?)""",
        (NOW,),
    )
    conn.execute(
        """INSERT INTO screenshot_georeferences
           (screenshot_id, georef_version, status, method, viewport_profile,
            viewport_x, viewport_y, viewport_w, viewport_h, anchor_count,
            lon0, dlon_dx, lat0, dlat_dy, scale_m_per_px, zoom_rung,
            zoom_support, confidence, estimated_error_m, evidence_json,
            observed_at)
           VALUES (1, 'rlsm-spatial-georef-v1', 'located',
                   'multi_anchor_affine', '200x400:0,20,200,240', 0, 20,
                   200, 240, 3, -67, 0.001, 19, -0.001, 100, 0, 3,
                   0.9, 120, '{}', ?)""",
        (NOW,),
    )
    conn.execute(
        """INSERT INTO zoom_ladder_rungs
           (georef_version, viewport_profile, zoom_rung, scale_m_per_px,
            dlon_dx, dlat_dy, support_count, dispersion_log2,
            eligible_for_transfer, evidence_json, observed_at)
           VALUES ('rlsm-spatial-georef-v1', '200x400:0,20,200,240', 0,
                   100, 0.001, -0.001, 3, 0.01, 1, '{}', ?)""",
        (NOW,),
    )
    conn.commit()
    conn.close()


def test_spatial_loaders_expose_bounded_rows_and_keep_heading_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "rlsm.sqlite"
    _fixture_db(db)
    monkeypatch.setattr(backend, "RLSM_DB", db)

    observations = backend.load_rlsm_spatial_observations()
    assert len(observations) == 1
    row = observations[0]
    assert row["registration"] == "N123AB"
    assert row["heading_deg"] == 137
    assert row["icon_rotation_deg"] == 42
    assert row["position_error_m"] == 120
    assert row["source_type"] == "fr24_screenshot"
    assert row["synthetic_flag"] is False

    frames = backend.load_rlsm_spatial_frames()
    assert len(frames) == 1
    assert frames[0]["marker_status"] == "selected"
    assert frames[0]["georef_method"] == "multi_anchor_affine"

    rungs = backend.load_rlsm_zoom_rungs()
    assert len(rungs) == 1
    assert rungs[0]["eligible_for_transfer"] is True

    profiles = backend.load_aircraft_profiles()
    assert [profile["tail_number"] for profile in profiles] == ["N123AB"]


def test_entity_api_reaches_spatial_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient

    db = tmp_path / "rlsm.sqlite"
    _fixture_db(db)
    monkeypatch.setattr(backend, "RLSM_DB", db)

    with TestClient(backend.app) as client:
        frames = client.get("/api/entities/RLSMSpatialFrames")
        rungs = client.get("/api/entities/RLSMZoomRungs")
        spatial_observations = client.get("/api/entities/RLSMSpatialObservations")
        observations = client.get("/api/entities/AirspaceObservations")

    assert (
        frames.status_code
        == rungs.status_code
        == spatial_observations.status_code
        == observations.status_code
        == 200
    )
    assert frames.json()[0]["marker_status"] == "selected"
    assert rungs.json()[0]["eligible_for_transfer"] is True
    assert spatial_observations.json()[0]["observation_id"] == "rlsm-aircraft-1"
    assert any(row.get("observation_id") == "rlsm-aircraft-1" for row in observations.json())


def test_committed_craft_profiles_replace_matching_whole_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "rlsm.sqlite"
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    _fixture_db(db)
    committed = {
        "registration": "N123AB",
        "data_source": "known_db",
        "confidence_level": 0.95,
        "mission_is_authoritative": False,
        "primary_mission": "must-not-surface",
        "total_observations": 7,
    }
    (profile_dir / "N123AB.json").write_text(json.dumps(committed))
    (profile_dir / "N999XY.json").write_text(json.dumps({**committed, "registration": "N999XY"}))
    monkeypatch.setattr(backend, "RLSM_DB", db)
    monkeypatch.setattr(backend, "CRAFT_PROFILE_DIR", profile_dir)

    profiles = backend.load_aircraft_profiles()

    assert [row["registration"] for row in profiles] == ["N123AB", "N999XY"]
    assert profiles[0]["id"] == "N123AB"
    assert profiles[0]["observation_count"] == 7
    assert profiles[0]["mission_category"] is None


def test_query_api_uses_configured_profiles_and_offline_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient

    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    profile = {
        "registration": "N123AB",
        "data_source": "unknown",
        "profile_confidence_grade": "LOW",
        "coverage_gaps": ["fixture_gap"],
        "schedule": None,
    }
    (profile_dir / "N123AB.json").write_text(json.dumps(profile))
    monkeypatch.setattr(backend, "RLSM_DB", tmp_path / "missing.sqlite")
    monkeypatch.setattr(backend, "CRAFT_PROFILE_DIR", profile_dir)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with TestClient(backend.app) as client:
        missing = client.post("/api/query", json={})
        answer = client.post(
            "/api/query",
            json={"prompt": "schedule for N123AB", "natural_language": True},
        )

    assert missing.status_code == 400
    assert answer.status_code == 200
    assert answer.json()["craft"] == "N123AB"
    assert "Insufficient evidence" in answer.json()["text"]
