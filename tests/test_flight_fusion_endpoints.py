"""Tests for strategy #3 — wave fusion + endpoint matching.

Covers fr24/flight_fusion.py (multi-frame fusion, adapter-row shaping),
fr24/endpoint_matcher.py (haversine banding vs the real airport registry,
flight_endpoint_event schema conformance), and the spiderweb adapter honoring
fused num_screenshots while keeping single-frame behavior identical.
"""
from __future__ import annotations

import json
from pathlib import Path

from fr24.endpoint_matcher import (
    endpoint_events_for_wave,
    facility_code,
    haversine_m,
    load_airports,
    match_endpoint,
    schema_fields,
)
from fr24.flight_fusion import fuse_rows, fuse_wave, to_adapter_row
from fr24.spiderweb_adapter import map_to_flight_event

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (REPO_ROOT / "schemas" / "flight_endpoint_event.schema.json").read_text()
)

SJU = (18.4394, -66.0018)


def _row(image: str, iso: str, *, registration: str = "N407PR",
         lat: float | None = None, lon: float | None = None, **extra) -> dict:
    row = {
        "image_name": image,
        "registration": registration,
        "callsign_or_label": registration,
        "vector_playback_iso": iso,
        "vector_max_confidence": 0.8,
    }
    if lat is not None:
        row["lat"] = lat
    if lon is not None:
        row["lon"] = lon
    row.update(extra)
    return row


WAVE_ROWS = [
    _row("b.HEIC", "2026-03-24T09:45:00", lat=18.42, lon=-66.05,
         barometric_altitude_ft="1500"),
    _row("a.HEIC", "2026-03-24T09:40:00", lat=SJU[0], lon=SJU[1],
         barometric_altitude_ft="1200", origin_code="SJU"),
    _row("c.HEIC", "2026-03-24T09:52:00", lat=18.008, lon=-66.563,
         ground_speed_mph="120"),
]


# ──────────────────────────────────────────────────────────────────────────
# fusion
# ──────────────────────────────────────────────────────────────────────────

def test_fuse_wave_orders_points_and_counts_frames():
    fused = fuse_wave(WAVE_ROWS)
    assert fused["num_screenshots"] == 3
    assert fused["first_seen_iso"] == "2026-03-24T09:40:00"
    assert fused["last_seen_iso"] == "2026-03-24T09:52:00"
    assert fused["duration_minutes"] == 12.0
    assert [p["image_name"] for p in fused["points"]] == ["a.HEIC", "b.HEIC", "c.HEIC"]
    assert fused["registration"] == "N407PR"
    assert fused["max_altitude_ft"] == 1500
    assert fused["confidence"] == 0.8
    assert fused["confirmation_status"] == "not_confirmed"


def test_fuse_rows_groups_by_identity():
    other = _row("z.HEIC", "2026-03-24T10:00:00", registration="N123AB")
    fused = fuse_rows(WAVE_ROWS + [other])
    by_identity = {f["aircraft_identity"]: f for f in fused}
    assert set(by_identity) == {"N407PR", "N123AB"}
    assert by_identity["N407PR"]["num_screenshots"] == 3
    assert by_identity["N123AB"]["num_screenshots"] == 1


def test_fuse_wave_missing_coordinates_stay_none():
    fused = fuse_wave([_row("a.HEIC", "2026-03-24T09:40:00")])
    assert fused["points"][0]["lat"] is None
    assert fused["points"][0]["lon"] is None


# ──────────────────────────────────────────────────────────────────────────
# endpoint matching vs the real registry
# ──────────────────────────────────────────────────────────────────────────

def test_haversine_zero_and_known_distance():
    assert haversine_m(*SJU, *SJU) == 0.0
    # SJU <-> Mercedita (PSE) is ~75 km
    assert 60_000 < haversine_m(*SJU, 18.0083, -66.5630) < 90_000


def test_match_endpoint_bands():
    airports = load_airports()
    exact = match_endpoint(*SJU, airports)
    assert exact is not None
    airport, distance, confidence = exact
    assert airport["airport_id"] == "airport_sju_tjsj"
    assert distance < 100 and confidence == 0.7

    # ~5 km east of SJU: weak band
    weak = match_endpoint(18.4394, -65.9545, airports)
    assert weak is not None
    _, weak_distance, weak_confidence = weak
    assert 3_000 < weak_distance <= 10_000 and weak_confidence == 0.4

    # Offshore, far from every registry facility
    assert match_endpoint(17.0, -68.5, airports) is None


def _assert_schema_conformant(event: dict) -> None:
    properties = SCHEMA["properties"]
    for field in SCHEMA["required"]:
        assert field in event, f"missing required field {field}"
    assert set(event) <= set(properties), f"extra fields: {set(event) - set(properties)}"
    for field, spec in properties.items():
        if field not in event or "enum" not in spec:
            continue
        assert event[field] in spec["enum"], f"{field}={event[field]} not in enum"
    assert isinstance(event["distance_m"], (int, float)) and event["distance_m"] >= 0
    assert 0 <= event["confidence"] <= 1
    assert isinstance(event["synthetic"], bool)


def test_endpoint_events_expose_check3_fields_and_validate():
    airports = load_airports()
    fused = fuse_wave(WAVE_ROWS)  # starts at SJU, ends near Mercedita
    events = endpoint_events_for_wave(
        fused, airports, observation_id="fr24-wave-1", source_id="src-wave-1",
        lineage_id="lin-wave-1", synthetic=True,
    )
    assert [e["endpoint_type"] for e in events] == ["start", "end"]
    start, end = events
    assert start["matched_facility_id"] == "airport_sju_tjsj"
    assert end["matched_facility_id"] == "airport_pse_tjps"
    for event in events:
        # docs/FR24_NON_SYNTHETIC_EXPORT_PLAN.md check #3
        for field in ("match_method", "distance_m", "matched_facility_id",
                      "confidence", "review_status"):
            assert event.get(field) not in (None, "")
        assert event["match_method"] == "track_endpoint_distance"
        assert event["review_status"] == "needs_review"
        _assert_schema_conformant(schema_fields(event))


def test_single_frame_wave_yields_overflight_event():
    airports = load_airports()
    fused = fuse_wave([_row("a.HEIC", "2026-03-24T09:40:00", lat=SJU[0], lon=SJU[1])])
    events = endpoint_events_for_wave(
        fused, airports, observation_id="fr24-1", source_id="s", lineage_id="l",
        synthetic=True,
    )
    assert len(events) == 1
    assert events[0]["endpoint_type"] == "overflight_near_facility"
    _assert_schema_conformant(schema_fields(events[0]))


def test_offshore_or_coordless_waves_yield_no_events():
    airports = load_airports()
    offshore = fuse_wave([_row("a.HEIC", "2026-03-24T09:40:00", lat=17.0, lon=-68.5)])
    coordless = fuse_wave([_row("b.HEIC", "2026-03-24T09:41:00")])
    for fused in (offshore, coordless):
        assert endpoint_events_for_wave(
            fused, airports, observation_id="x", source_id="s", lineage_id="l",
            synthetic=True,
        ) == []


# ──────────────────────────────────────────────────────────────────────────
# adapter integration
# ──────────────────────────────────────────────────────────────────────────

def test_adapter_row_carries_fused_endpoints_into_flight_event():
    airports = load_airports()
    fused = fuse_wave(WAVE_ROWS)
    events = endpoint_events_for_wave(
        fused, airports, observation_id="fr24-wave-1", source_id="s",
        lineage_id="l", synthetic=True,
    )
    adapter_row = to_adapter_row(fused, selection_status="selected_candidate",
                                 endpoint_events=events)
    assert adapter_row["num_screenshots"] == 3
    assert adapter_row["origin_code"] == "SJU"
    assert adapter_row["destination_code"] == facility_code(
        {"iata": "PSE", "icao": "TJPS", "airport_id": "airport_pse_tjps"}
    )

    mapped = map_to_flight_event(adapter_row)
    assert mapped["num_screenshots"] == 3
    assert mapped["origin_airport"] == "SJU"
    assert mapped["destination_airport"] == "PSE"
    assert mapped["confirmation_status"] == "not_confirmed"


def test_adapter_single_frame_behavior_unchanged():
    plain = {
        "candidate_id": "cand-1",
        "callsign_or_label": "N407PR",
        "playback_date": "2026-03-24",
        "playback_time": "09:40",
    }
    mapped = map_to_flight_event(plain)
    assert mapped["num_screenshots"] == 1
    assert mapped["confirmation_status"] == "not_confirmed"


def test_adapter_rejects_bogus_num_screenshots():
    mapped = map_to_flight_event({"candidate_id": "c", "callsign_or_label": "N1",
                                  "num_screenshots": "not-a-number"})
    assert mapped["num_screenshots"] == 1
