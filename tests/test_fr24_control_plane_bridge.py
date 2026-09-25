import csv
import json
import sqlite3
from pathlib import Path

from server.backend.console.fr24_control_plane import ingest_fr24_control_plane
from server.backend.console.repositories import RepositoryRegistry

FLIGHT_FIELDS = [
    "flight_id",
    "registration",
    "callsign",
    "icao24",
    "aircraft_type",
    "first_seen_at_utc",
    "last_seen_at_utc",
    "status",
]
TRACK_FIELDS = [
    "track_point_id",
    "flight_id",
    "observed_at_utc",
    "lat",
    "lon",
    "altitude_ft",
    "speed_kt",
    "heading_deg",
    "registration",
    "callsign",
    "icao24",
    "aircraft_type",
]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def make_exports(
    tmp_path: Path,
    *,
    callsign: str,
    include_points: bool = True,
) -> tuple[Path, Path]:
    flight_summary = tmp_path / f"flight_summary_{callsign or 'blank'}.csv"
    track_points = tmp_path / f"track_points_{callsign or 'blank'}.csv"
    write_csv(
        flight_summary,
        FLIGHT_FIELDS,
        [
            {
                "flight_id": "416abc01",
                "registration": "N600UH",
                "callsign": callsign,
                "icao24": "A7C001",
                "aircraft_type": "C172",
                "first_seen_at_utc": "2026-09-09T12:00:00Z",
                "last_seen_at_utc": "2026-09-09T12:05:00Z",
                "status": "completed",
            }
        ],
    )
    rows = []
    if include_points:
        rows = [
            {
                "track_point_id": "tp-1",
                "flight_id": "416abc01",
                "observed_at_utc": "2026-09-09T12:00:00Z",
                "lat": 18.45,
                "lon": -66.10,
                "altitude_ft": 1200,
                "speed_kt": 95,
                "heading_deg": 180,
                "registration": "N600UH",
                "callsign": callsign,
                "icao24": "A7C001",
                "aircraft_type": "C172",
            },
            {
                "track_point_id": "tp-2",
                "flight_id": "416abc01",
                "observed_at_utc": "2026-09-09T12:05:00Z",
                "lat": 18.46,
                "lon": -66.11,
                "altitude_ft": 1300,
                "speed_kt": 100,
                "heading_deg": 185,
                "registration": "N600UH",
                "callsign": callsign,
                "icao24": "A7C001",
                "aircraft_type": "C172",
            },
        ]
    write_csv(track_points, TRACK_FIELDS, rows)
    return flight_summary, track_points


def test_control_plane_bridge_preserves_n600uh_identity_end_to_end(tmp_path, monkeypatch):
    flight_summary, track_points = make_exports(tmp_path, callsign="N600UH")
    db_path = tmp_path / "flight_database.db"
    connection = sqlite3.connect(db_path)
    try:
        summary = ingest_fr24_control_plane(
            connection,
            flight_summary=flight_summary,
            track_points=track_points,
        )
        row = connection.execute(
            """
            SELECT aircraft_id, icao24, registration, callsign, aircraft_type, provenance_json
            FROM console_flight_sessions WHERE flight_id='416abc01'
            """
        ).fetchone()
    finally:
        connection.close()

    assert summary.flight_sessions_written == 1
    assert summary.track_points_written == 2
    assert summary.identity_survival_failures == 0
    assert row is not None
    assert row[0:5] == ("A7C001", "A7C001", "N600UH", "N600UH", "C172")
    provenance = json.loads(row[5])
    assert provenance["identity_state"] == "SOURCE_IDENTITY_PRESENT"
    assert provenance["identity_observations"]["callsign"] == ["N600UH"]

    monkeypatch.setenv("SKYWATCHER_FLIGHT_DB", str(db_path))
    registry = RepositoryRegistry(tmp_path)

    session = registry.snapshot("flight_sessions").rows[0]
    assert session["registration"] == "N600UH"
    assert session["callsign"] == "N600UH"
    assert session["icao24"] == "A7C001"
    assert session["provenance"]["source_method"] == "control_plane_export"
    assert "invalid_source_method_normalized_to_unknown" not in session["qa_flags"]

    points = registry.snapshot("track_points").rows
    assert len(points) == 2
    assert {point["registration"] for point in points} == {"N600UH"}
    assert {point["callsign"] for point in points} == {"N600UH"}
    assert {point["icao24"] for point in points} == {"A7C001"}


def test_blank_reobservation_does_not_erase_existing_callsign(tmp_path):
    db_path = tmp_path / "flight_database.db"
    connection = sqlite3.connect(db_path)
    try:
        first_summary, first_points = make_exports(tmp_path, callsign="N600UH")
        ingest_fr24_control_plane(
            connection,
            flight_summary=first_summary,
            track_points=first_points,
        )

        second_summary, second_points = make_exports(
            tmp_path,
            callsign="",
            include_points=False,
        )
        ingest_fr24_control_plane(
            connection,
            flight_summary=second_summary,
            track_points=second_points,
        )

        row = connection.execute(
            """
            SELECT callsign, max_altitude_ft, max_ground_speed_kt
            FROM console_flight_sessions WHERE flight_id='416abc01'
            """
        ).fetchone()
    finally:
        connection.close()

    assert row == ("N600UH", 1300.0, 100.0)


def test_conflicting_nonblank_callsigns_are_preserved_and_fail_closed(tmp_path, monkeypatch):
    db_path = tmp_path / "flight_database.db"
    connection = sqlite3.connect(db_path)
    try:
        first_summary, first_points = make_exports(tmp_path, callsign="N600UH")
        ingest_fr24_control_plane(
            connection,
            flight_summary=first_summary,
            track_points=first_points,
        )

        conflict_summary, conflict_points = make_exports(
            tmp_path,
            callsign="TEST123",
            include_points=False,
        )
        summary = ingest_fr24_control_plane(
            connection,
            flight_summary=conflict_summary,
            track_points=conflict_points,
        )
        row = connection.execute(
            """
            SELECT registration, callsign, provenance_json
            FROM console_flight_sessions WHERE flight_id='416abc01'
            """
        ).fetchone()
    finally:
        connection.close()

    assert summary.identity_conflict_flights == 1
    assert row is not None
    assert row[0] == "N600UH"
    assert row[1] is None
    provenance = json.loads(row[2])
    assert provenance["identity_state"] == "UNRESOLVED_CONFLICT"
    assert provenance["identity_conflicts"] == ["callsign"]
    assert provenance["identity_observations"]["callsign"] == ["TEST123", "N600UH"]

    monkeypatch.setenv("SKYWATCHER_FLIGHT_DB", str(db_path))
    session = RepositoryRegistry(tmp_path).snapshot("flight_sessions").rows[0]
    assert session["callsign"] is None
    assert session["identity_state"] == "UNRESOLVED_CONFLICT"
    assert session["identity_observations"]["callsign"] == ["TEST123", "N600UH"]
    assert "identity_callsign_conflict" in session["qa_flags"]
