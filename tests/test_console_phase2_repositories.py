import json
import sqlite3
from pathlib import Path

from server.backend.console.migrations import migrate
from server.backend.console.repositories import RepositoryRegistry


def build_flight_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    migrate(connection)
    connection.executescript(
        """
        CREATE TABLE screenshots (
            screenshot_id TEXT PRIMARY KEY,
            image_path TEXT,
            processed_at TEXT,
            sha256 TEXT,
            review_status TEXT
        );
        CREATE TABLE track_points (
            id INTEGER PRIMARY KEY,
            flight_id TEXT,
            timestamp TEXT,
            latitude REAL,
            longitude REAL,
            altitude_ft INTEGER,
            ground_speed_mph INTEGER
        );
        CREATE TABLE flights (
            flight_id TEXT PRIMARY KEY,
            callsign TEXT,
            registration TEXT,
            aircraft_type TEXT,
            operator TEXT,
            origin TEXT,
            destination TEXT,
            takeoff_time TEXT,
            landing_time TEXT,
            status TEXT
        );
        CREATE TABLE aircraft_profiles (
            callsign TEXT PRIMARY KEY,
            aircraft_type TEXT,
            owner TEXT,
            operator TEXT,
            primary_mission TEXT,
            confidence_level REAL,
            total_flights INTEGER,
            first_seen TEXT,
            last_seen TEXT,
            operational_patterns TEXT
        );
        """
    )
    connection.execute(
        "INSERT INTO screenshots VALUES (?, ?, ?, ?, ?)",
        ("shot-1", "/evidence/shot-1.png", "2026-07-20T16:00:00Z", "a" * 64, "pending"),
    )
    connection.execute(
        "INSERT INTO track_points VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "flight-1", "2026-07-20T16:00:00Z", 18.4, -66.0, 5000, 120),
    )
    connection.execute(
        "INSERT INTO track_points VALUES (?, ?, ?, ?, ?, ?, ?)",
        (2, "flight-1", "2026-07-20T16:05:00", 18.5, -66.1, 5100, 125),
    )
    connection.execute(
        "INSERT INTO flights VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "flight-1",
            "TEST1",
            "N100AA",
            "H125",
            "Test Operator",
            "TJSJ",
            "TJPS",
            "2026-07-20T16:00:00Z",
            "2026-07-20T16:30:00Z",
            "completed",
        ),
    )
    connection.execute(
        "INSERT INTO aircraft_profiles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "TEST1",
            "H125",
            "Test Owner",
            "Test Operator",
            "Unknown",
            0.8,
            1,
            "2026-07-20T16:00:00Z",
            "2026-07-20T16:30:00Z",
            json.dumps({"fixture": True}),
        ),
    )
    provenance = json.dumps(
        {
            "source_family": "official_record",
            "source_provider": "fixture-airport-provider",
            "source_method": "airport_operations",
            "data_rights": "public_official",
            "operational_mode": "historical",
            "source_record_id": "airport-state-1",
            "lineage_id": "lineage-airport-state-1",
            "artifact_path": str(path),
            "ingest_adapter": "fixture",
        }
    )
    connection.execute(
        """
        INSERT INTO console_airport_operational_states(
          airport_state_id, airport_id, observed_at_utc, operational_status,
          departures_count, arrivals_count, on_ground_count, delay_minutes,
          disruption_codes_json, weather_json, events_json,
          source_family, source_provider, source_method, data_rights,
          operational_mode, source_record_id, lineage_id, provenance_json, synthetic
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "airport-state-1",
            "TJSJ",
            "2026-07-20T16:00:00Z",
            "normal",
            10,
            11,
            4,
            0,
            "[]",
            json.dumps({"metar_raw": "TJSJ 201556Z"}),
            "[]",
            "official_record",
            "fixture-airport-provider",
            "airport_operations",
            "public_official",
            "historical",
            "airport-state-1",
            "lineage-airport-state-1",
            provenance,
            0,
        ),
    )
    connection.commit()
    connection.close()


def build_review_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE review_queue (
            item_id TEXT PRIMARY KEY,
            queue_type TEXT NOT NULL,
            image_path TEXT NOT NULL,
            reason TEXT NOT NULL,
            metadata TEXT,
            status TEXT,
            resolution TEXT,
            reviewer_notes TEXT,
            created_at TEXT,
            reviewed_at TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO review_queue VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "review-1",
            "route_georef",
            "/evidence/shot-1.png",
            "Needs control points",
            "{}",
            "pending",
            None,
            None,
            "2026-07-20T16:10:00Z",
            None,
        ),
    )
    connection.commit()
    connection.close()


def test_phase2_repositories_load_bounded_artifacts_with_complete_provenance(tmp_path, monkeypatch):
    flight_db = tmp_path / "flight_database.db"
    review_db = tmp_path / "review_queue.db"
    build_flight_db(flight_db)
    build_review_db(review_db)
    monkeypatch.setenv("SKYWATCHER_FLIGHT_DB", str(flight_db))
    monkeypatch.setenv("SKYWATCHER_REVIEW_QUEUE", str(review_db))

    registry = RepositoryRegistry(tmp_path)
    expected = {
        "fr24_captures": 1,
        "manual_review_items": 1,
        "aircraft_profiles": 1,
        "track_points": 1,
        "route_segments": 1,
        "flight_sessions": 1,
        "aircraft_states": 1,
        "airport_operational_states": 1,
    }
    for repository, count in expected.items():
        snapshot = registry.snapshot(repository)
        assert snapshot.record_count == count, repository
        assert snapshot.provenance_complete is True, repository
        assert snapshot.status in {"available", "degraded"}, repository
        assert snapshot.reason

    track = registry.snapshot("track_points")
    assert track.skipped_rows == 1
    assert track.status == "degraded"
    assert "legacy_screenshot_route_export" in track.rows[0]["qa_flags"]
    assert track.rows[0]["measurement_status"] == "derived_from_screenshot"


def test_empty_repository_statuses_are_explicit(tmp_path, monkeypatch):
    for variable in (
        "SKYWATCHER_FLIGHT_DB",
        "SKYWATCHER_REVIEW_QUEUE",
        "SKYWATCHER_FR24_CAPTURE_INVENTORY",
        "SKYWATCHER_TRACK_ARTIFACT",
        "SKYWATCHER_FLIGHT_SESSIONS",
        "SKYWATCHER_AIRCRAFT_PROFILES",
        "SKYWATCHER_AIRPORT_STATES",
    ):
        monkeypatch.delenv(variable, raising=False)
    registry = RepositoryRegistry(tmp_path)
    for status in registry.statuses():
        assert status["status"] in {"unavailable_no_artifact", "available_synthetic_only"}
        assert status["reason"]
        assert status["provenance_complete"] is True
