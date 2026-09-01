import json
from pathlib import Path

from scripts.federation_export import build_streams

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas"

OBS = [{
    "observation_id": "o1", "event_datetime": "2026-05-20T10:00:00Z",
    "location_name": "San Juan point", "municipality": "San Juan",
    "lat": "18.4", "lon": "-66.0", "altitude_ft": "2500", "bearing": "90",
    "duration_seconds": "180", "signal_type": "FR24_SCREENSHOT",
    "source_id": "s1", "source_type": "screenshot", "evidence_tier": "T2",
    "confidence": "0.82", "geometry_status": "approximate", "temporal_status": "exact",
    "lineage_id": "l1", "synthetic": "false",
}]
SRC = [{
    "source_id": "s1", "source_type": "screenshot", "source_path": "fr24.png",
    "sha256": "abc123", "retrieved_at": "2026-05-20T00:00:00Z", "provenance_status": "verified",
}]
ALERTS = [{
    "alert_id": "a1", "source_id": "s1", "observation_id": "o1",
    "module": "AIRSPACE_OPS", "alert_type": "loitering_pattern",
    "anomaly_kind": "repeated_orbit", "severity": 2, "status": "draft",
    "event_datetime": "2026-05-20T10:05:00Z", "lat": "18.4", "lon": "-66.0",
    "municipality": "San Juan", "evidence_tier": "T2", "confidence": "0.71",
    "synthetic": "false",
}]


def _validator(schema_file):
    from jsonschema import Draft7Validator

    schema = json.loads((SCHEMA_DIR / schema_file).read_text())
    return Draft7Validator(schema)


def test_stream_shapes():
    s = build_streams(OBS, SRC, "2026-01-01T00:00:00Z")
    assert {e["entity_type"] for e in s["entities"]} == {"airspace_observation", "sensor_source", "municipality"}
    assert all(e["entity_id"].startswith("ent_") for e in s["entities"])
    assert len(s["sources"]) == 1 and s["sources"][0]["source_id"].startswith("src_")
    assert {r["relationship_type"] for r in s["relationships"]} == {"detected_by", "located_in"}
    assert all(r["relationship_id"].startswith("rel_") for r in s["relationships"])


def test_deterministic_ids():
    a = build_streams(OBS, SRC, "t")
    b = build_streams(OBS, SRC, "t")
    assert [e["entity_id"] for e in a["entities"]] == [e["entity_id"] for e in b["entities"]]


def test_verified_source_not_synthetic():
    s = build_streams(OBS, SRC, "t")
    assert all(not r["synthetic"] for r in s["entities"])
    assert all(not r["synthetic"] for r in s["sources"])


def test_observation_carries_location():
    # Z2: lat/lon (CSV strings) are coerced onto the canonical entity location.
    s = build_streams(OBS, SRC, "t")
    obs_ent = next(e for e in s["entities"] if e["entity_type"] == "airspace_observation")
    assert obs_ent["location"] == {"lat": 18.4, "lon": -66.0, "municipality": "San Juan"}
    # source/municipality entities carry no point location
    assert all(
        "location" not in e
        for e in s["entities"]
        if e["entity_type"] != "airspace_observation"
    )


# ── FE1: canonical observations stream ────────────────────────────────────────

def test_observations_stream_shape_and_ids():
    s = build_streams(OBS, SRC, "2026-01-01T00:00:00Z")
    assert len(s["observations"]) == 1
    o = s["observations"][0]
    # obs_<32hex> per the Hub federation_observation contract.
    assert o["observation_id"].startswith("obs_") and len(o["observation_id"]) == 36
    # anchored to the matching airspace_observation entity.
    obs_ent = next(e for e in s["entities"] if e["entity_type"] == "airspace_observation")
    assert o["entity_id"] == obs_ent["entity_id"]
    # signal_type projected to a stable slug as the observation category.
    assert o["observation_type"] == "fr24_screenshot"
    # location carries the point + altitude for cross-producer spatial joins.
    assert o["location"] == {"lat": 18.4, "lon": -66.0, "municipality": "San Juan", "altitude_ft": 2500.0}
    # airspace-specific fields ride in attributes, not dropped.
    assert o["attributes"]["signal_type"] == "FR24_SCREENSHOT"
    assert o["attributes"]["evidence_tier"] == "T2"
    assert o["attributes"]["bearing"] == 90.0


def test_observations_validate_against_hub_schema():
    s = build_streams(OBS, SRC, "2026-01-01T00:00:00Z")
    v = _validator("federation_observation.schema.json")
    for o in s["observations"]:
        assert not list(v.iter_errors(o)), list(v.iter_errors(o))


def test_observation_ids_deterministic():
    a = build_streams(OBS, SRC, "t")
    b = build_streams(OBS, SRC, "t")
    assert [o["observation_id"] for o in a["observations"]] == [o["observation_id"] for o in b["observations"]]


# ── FE2: canonical alerts stream ──────────────────────────────────────────────

def test_alerts_stream_shape_and_guardrails():
    s = build_streams(OBS, SRC, "2026-01-01T00:00:00Z", alerts=ALERTS)
    assert len(s["alerts"]) == 1
    a = s["alerts"][0]
    # alrt_<32hex> per the Hub federation_alert contract.
    assert a["alert_id"].startswith("alrt_") and len(a["alert_id"]) == 37
    assert a["severity"] == 2 and a["status"] == "draft"
    # anchored to the airspace_observation entity it is about.
    obs_ent = next(e for e in s["entities"] if e["entity_type"] == "airspace_observation")
    assert a["entity_id"] == obs_ent["entity_id"]
    # review-only guardrail posture is always stamped (defense-in-depth).
    assert a["attributes"]["operator_action"] == "review_context_only"
    assert a["attributes"]["operational_cueing"] is False
    assert a["attributes"]["confirmation_status"] == "not_confirmed"


def test_alerts_validate_against_hub_schema():
    s = build_streams(OBS, SRC, "2026-01-01T00:00:00Z", alerts=ALERTS)
    v = _validator("federation_alert.schema.json")
    for a in s["alerts"]:
        assert not list(v.iter_errors(a)), list(v.iter_errors(a))


def test_alert_severity_clamped_and_status_defaulted():
    bad = [dict(ALERTS[0], alert_id="a2", severity=99, status="bogus")]
    a = build_streams(OBS, SRC, "t", alerts=bad)["alerts"][0]
    assert a["severity"] == 5            # clamped into [0,5]
    assert a["status"] == "draft"        # unknown status falls back to the safe default


def test_no_alerts_yields_empty_stream():
    s = build_streams(OBS, SRC, "t")
    assert s["alerts"] == []
    # observations still emitted even with no alerts input.
    assert len(s["observations"]) == 1
