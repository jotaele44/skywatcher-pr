"""Gate: Skywatcher bridge export validates against the shared schema."""

from __future__ import annotations

import json

from skywatcher.fr24 import database_migrations as migrations
from skywatcher.fr24 import database as db
from skywatcher.fr24 import spiderweb_export as se


def _synthetic_flight():
    return {
        "flight_id": "FL_TEST",
        "registration": "N123",
        "takeoff_time": "2026-01-01T00:00:00Z",
        "landing_time": "2026-01-01T00:20:00Z",
        "confidence": 0.72,
        "review_status": "promoted",
        "coordinate_method": "per_screenshot_affine",
        "mission_type": "patrol",
        "mission_confidence": 0.9,
    }


def test_build_bridge_record_is_schema_valid():
    rec = se.build_bridge_record(
        _synthetic_flight(),
        [{"latitude": 18.1, "longitude": -66.0}, {"latitude": 18.2, "longitude": -66.1}],
        export_id="pkg_" + "a" * 32,
        source_snapshot_id="snap1",
        generated_at_utc="2026-01-01T01:00:00Z",
    )
    assert se.validate_bridge_record(rec) == []
    # C3: confidence wrapped as {score, method}
    assert set(rec["confidence"]) == {"score", "method"}
    # C4: review_status crosswalked (promoted -> approved)
    assert rec["review_status"] == "approved"
    # C1: mission gated
    assert rec["mission_classification"]["status"] in ("highly_speculative", "evidence_gated")
    # C2: no 'confirmed' terminal-accept token
    assert rec["review_status"] != "confirmed"


def test_export_package_roundtrip(tmp_path):
    dbp = tmp_path / "s.db"
    migrations.initialize_database(dbp)
    conn = db.connect(dbp)
    try:
        f = _synthetic_flight()
        conn.execute(
            "INSERT INTO flights (flight_id, takeoff_time, landing_time, confidence, "
            "review_status, coordinate_method, mission_type, mission_confidence, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (f["flight_id"], f["takeoff_time"], f["landing_time"], f["confidence"],
             f["review_status"], f["coordinate_method"], f["mission_type"],
             f["mission_confidence"], "2026-01-01T01:00:00Z"),
        )
        conn.execute("INSERT INTO track_points (flight_id, seq, latitude, longitude) VALUES ('FL_TEST',0,18.1,-66.0)")
        conn.execute("INSERT INTO track_points (flight_id, seq, latitude, longitude) VALUES ('FL_TEST',1,18.2,-66.1)")
        conn.commit()
    finally:
        conn.close()

    out = se.export_package(dbp, tmp_path / "pkg", source_snapshot_id="snap1",
                            generated_at_utc="2026-01-01T01:00:00Z")
    manifest = json.loads((tmp_path / "pkg" / "manifest.json").read_text())
    assert manifest["record_counts"]["flights"] == 1
    assert manifest["export_id"].startswith("pkg_")
    lines = (tmp_path / "pkg" / "bridge_records.jsonl").read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert se.validate_bridge_record(rec) == []
    assert rec["validated_track_geometry"]["type"] == "LineString"


def test_empty_export_reports_zero(tmp_path):
    dbp = tmp_path / "s.db"
    migrations.initialize_database(dbp)
    out = se.export_package(dbp, tmp_path / "pkg", source_snapshot_id="snap0",
                            generated_at_utc="2026-01-01T01:00:00Z")
    manifest = json.loads((tmp_path / "pkg" / "manifest.json").read_text())
    assert manifest["record_counts"]["flights"] == 0  # empty, honestly reported
