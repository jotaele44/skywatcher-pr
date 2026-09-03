import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from server.backend.console.migrations import migrate
from server.backend.main import app


def build_console_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    migrate(connection)
    provenance = json.dumps(
        {
            "source_family": "operational_position",
            "source_provider": "fixture-receiver",
            "source_method": "adsb",
            "data_rights": "owned",
            "operational_mode": "historical",
            "source_record_id": "state-source",
            "lineage_id": "state-lineage",
            "artifact_path": str(path),
            "ingest_adapter": "fixture",
        }
    )
    for index in range(3):
        observed = f"2026-07-20T16:0{index}:00Z"
        connection.execute(
            """
            INSERT INTO console_track_points(
              track_point_id, flight_id, aircraft_id, observed_at_utc, lat, lon,
              measurement_status, source_family, source_provider, source_method,
              data_rights, operational_mode, source_record_id, lineage_id,
              provenance_json, synthetic
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"tp-{index}",
                "flight-api",
                "N200BB",
                observed,
                18.0 + index * 0.01,
                -66.0 - index * 0.01,
                "measured",
                "operational_position",
                "fixture-receiver",
                "adsb",
                "owned",
                "historical",
                f"tp-{index}",
                f"lineage-{index}",
                provenance,
                0,
            ),
        )
    connection.execute(
        """
        INSERT INTO console_flight_sessions(
          flight_id, aircraft_id, registration, callsign, first_seen_at_utc,
          last_seen_at_utc, status, point_count, track_quality, gap_count,
          source_family, source_provider, source_method, data_rights,
          operational_mode, source_record_id, lineage_id, provenance_json, synthetic
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "flight-api",
            "N200BB",
            "N200BB",
            "TEST200",
            "2026-07-20T16:00:00Z",
            "2026-07-20T16:02:00Z",
            "completed",
            3,
            "continuous",
            0,
            "operational_position",
            "fixture-receiver",
            "adsb",
            "owned",
            "historical",
            "flight-api",
            "flight-lineage",
            provenance,
            0,
        ),
    )
    connection.commit()
    connection.close()


def test_paginated_track_endpoint_has_stable_nonoverlapping_cursors(tmp_path, monkeypatch):
    db = tmp_path / "console.db"
    build_console_db(db)
    monkeypatch.setenv("SKYWATCHER_FLIGHT_DB", str(db))
    client = TestClient(app)

    first = client.get("/api/console/flights/flight-api/track?limit=2")
    assert first.status_code == 200
    payload1 = first.json()
    assert [row["track_point_id"] for row in payload1["items"]] == ["tp-0", "tp-1"]
    assert payload1["page"]["has_more"] is True
    cursor = payload1["page"]["next_cursor"]

    second = client.get("/api/console/flights/flight-api/track", params={"limit": 2, "cursor": cursor})
    assert second.status_code == 200
    payload2 = second.json()
    assert [row["track_point_id"] for row in payload2["items"]] == ["tp-2"]
    assert set(row["track_point_id"] for row in payload1["items"]).isdisjoint(
        row["track_point_id"] for row in payload2["items"]
    )


def test_console_rejects_naive_query_times(tmp_path, monkeypatch):
    db = tmp_path / "console.db"
    build_console_db(db)
    monkeypatch.setenv("SKYWATCHER_FLIGHT_DB", str(db))
    response = TestClient(app).get("/api/console/flights", params={"from": "2026-07-20T12:00:00"})
    assert response.status_code == 422
    assert "timezone" in response.json()["detail"]


def test_generic_entity_empty_collections_are_not_silent(tmp_path, monkeypatch):
    monkeypatch.setenv("SKYWATCHER_FLIGHT_DB", str(tmp_path / "missing.db"))
    client = TestClient(app)
    response = client.get("/api/entities/InfrastructureAssets")
    assert response.status_code == 200
    assert response.json() == []
    assert response.headers["x-skywatcher-availability"] == "unavailable_no_artifact"
    assert response.headers["x-skywatcher-availability-reason"]

    availability = client.get("/api/entities/InfrastructureAssets/availability")
    assert availability.status_code == 200
    assert availability.json()["reason"]


def test_generic_repository_entity_exposes_provenance_headers(tmp_path, monkeypatch):
    db = tmp_path / "console.db"
    build_console_db(db)
    connection = sqlite3.connect(db)
    connection.execute(
        "CREATE TABLE screenshots(screenshot_id TEXT PRIMARY KEY, image_path TEXT, processed_at TEXT, sha256 TEXT, review_status TEXT)"
    )
    connection.execute(
        "INSERT INTO screenshots VALUES (?, ?, ?, ?, ?)",
        ("cap-api", "/evidence/cap-api.png", "2026-07-20T16:00:00Z", "b" * 64, "pending"),
    )
    connection.commit()
    connection.close()
    monkeypatch.setenv("SKYWATCHER_FLIGHT_DB", str(db))

    response = TestClient(app).get("/api/entities/FR24Captures")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.headers["x-skywatcher-provenance-complete"] == "true"
    assert response.headers["x-skywatcher-availability"] == "available"
