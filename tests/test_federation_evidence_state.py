"""Additive evidence_state declarations (thehub-pr FEDERATION_EPISTEMIC_STATE_CONTRACT_V1).

Positive: observations declare class, presence, temporal precision and
geometry precision from their own source/geometry/temporal fields.
Negative: a screenshot-georeferenced point is never an observed point, an
unlocated observation never gets a geometry claim, an unknown source type
is never classified, and registry points never masquerade as observed.
"""

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.federation_export import EVIDENCE_STATE_CONTRACT, build_streams

REPO = Path(__file__).resolve().parent.parent
VENDORED = REPO / "schemas" / "federation_epistemic_state.v1.schema.json"
# sha256 of thehub-pr schemas/federation/epistemic_state.v1.schema.json (CANDIDATE).
HUB_CANDIDATE_SHA256 = "c31794807d47f00e9ffeb394cf9ddd5d093613dabcf22d4fd81d4a416bade088"
NOW = "2026-01-01T00:00:00Z"
SRC = [{"source_id": "s1", "source_type": "screenshot", "source_path": "fr24.png", "sha256": "abc",
        "retrieved_at": NOW, "provenance_status": "verified"}]


def _obs(**overrides):
    obs = {
        "observation_id": "o1", "event_datetime": "2026-05-20T10:00:00Z", "location_name": "San Juan point",
        "municipality": "San Juan", "lat": "18.4", "lon": "-66.0", "signal_type": "FR24_SCREENSHOT",
        "source_id": "s1", "source_type": "screenshot", "evidence_tier": "T2", "confidence": "0.8",
        "geometry_status": "approximate", "temporal_status": "exact", "synthetic": "false",
    }
    obs.update(overrides)
    return obs


def _state(**overrides):
    streams = build_streams([_obs(**overrides)], SRC, NOW)
    entity = next(e for e in streams["entities"] if e["entity_type"] == "airspace_observation")
    observation = streams["observations"][0]
    assert entity["evidence_state"] == observation["evidence_state"]
    return observation["evidence_state"]


def _validator():
    schema = json.loads(VENDORED.read_text())
    return Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"],
                                 "$ref": "#/$defs/producer_declaration"})


def test_vendored_contract_is_byte_identical_to_the_hub_candidate():
    assert hashlib.sha256(VENDORED.read_bytes()).hexdigest() == HUB_CANDIDATE_SHA256


def test_adsb_located_contact_is_a_measured_observed_point():
    state = _state(source_type="adsb", geometry_status="located")
    assert state["epistemic_class"] == "MEASURED"
    assert state["observation_state"] == "OBSERVED_PRESENT"
    assert (state["geometry_precision"], state["coordinate_method"]) == ("OBSERVED_POINT", "EXACT")
    assert state["temporal_precision"] == "EXACT_TIMESTAMP"


@pytest.mark.parametrize("geometry_status", ["located", "approximate"])
def test_screenshot_georeferenced_point_is_never_observed(geometry_status):
    state = _state(source_type="screenshot", geometry_status=geometry_status)
    assert state["geometry_precision"] == "INTERPRETED_POINT"
    assert state["epistemic_class"] == "MEASURED"


@pytest.mark.parametrize("geometry_status", ["unlocated", "invalid"])
def test_unlocated_observation_carries_no_geometry_claim(geometry_status):
    state = _state(geometry_status=geometry_status, lat="", lon="")
    assert "geometry_precision" not in state


def test_approximate_time_and_unknown_source_are_not_upgraded():
    state = _state(source_type="mystery", temporal_status="approximate")
    assert state["temporal_precision"] == "APPROXIMATE"
    assert "epistemic_class" not in state
    assert "observation_state" not in state
    assert "temporal_precision" not in _state(temporal_status="missing")


def test_registry_points_are_representative_and_computed_rows_are_computed():
    airfields = [{"facility_id": "TJSJ", "name": "SJU", "lat": 18.4394, "lon": -66.0018, "confidence": 0.9}]
    hangars = [{"zone_id": "Z1", "name_or_label": "Ramp", "lat": 18.44, "lon": -66.0}]
    endpoints = [{"endpoint_event_id": "e1", "source_id": "s1", "endpoint_type": "arrival",
                  "matched_facility_id": "TJSJ", "confidence": 0.6}]
    alerts = [{"alert_id": "a1", "source_id": "s1", "status": "draft", "event_datetime": NOW}]
    streams = build_streams([_obs()], SRC, NOW, airfields=airfields, hangar_zones=hangars,
                            endpoint_events=endpoints, alerts=alerts)
    by_type = {e["entity_type"]: e for e in streams["entities"]}
    assert by_type["airfield_registry"]["evidence_state"]["geometry_precision"] == "REPRESENTATIVE_POINT"
    assert by_type["hangar_zone"]["evidence_state"]["geometry_precision"] == "REPRESENTATIVE_POINT"
    assert by_type["flight_endpoint_event"]["evidence_state"]["epistemic_class"] == "COMPUTED"
    assert streams["alerts"][0]["evidence_state"]["epistemic_class"] == "COMPUTED"

    validator = _validator()
    rows = [row for rows in streams.values() for row in rows]
    assert all("evidence_state" in row for row in rows)
    for row in rows:
        assert row["evidence_state"]["contract"] == EVIDENCE_STATE_CONTRACT
        assert list(validator.iter_errors(row["evidence_state"])) == []
        assert row["evidence_state"].get("observation_state") != "OBSERVED_ABSENT"
