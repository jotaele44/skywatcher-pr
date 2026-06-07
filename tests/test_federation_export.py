from scripts.federation_export import build_streams

OBS = [{
    "observation_id": "o1", "event_datetime": "2026-05-20T10:00:00Z",
    "location_name": "San Juan point", "municipality": "San Juan",
    "lat": "18.4", "lon": "-66.0", "signal_type": "FR24_SCREENSHOT",
    "source_id": "s1", "source_type": "screenshot", "evidence_tier": "T2",
    "confidence": "0.82", "geometry_status": "approximate", "temporal_status": "exact",
    "lineage_id": "l1", "synthetic": "false",
}]
SRC = [{
    "source_id": "s1", "source_type": "screenshot", "source_path": "fr24.png",
    "sha256": "abc123", "retrieved_at": "2026-05-20T00:00:00Z", "provenance_status": "verified",
}]


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
