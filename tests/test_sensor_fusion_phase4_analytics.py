from scripts.build_sensor_fusion_visualization import build_visualization_payload
from scripts.export_sensor_fusion_thehub import build_thehub_export
from skywatcher.fusion.anomaly_scoring import score_against_historical_baselines
from skywatcher.fusion.historical_baselines import build_historical_baselines, index_baselines


def test_build_historical_baselines_groups_records_by_corridor_and_domain():
    baselines = build_historical_baselines([
        {"corridor_id": "sj_corridor", "domain": "air", "confidence": 0.8},
        {"corridor_id": "sj_corridor", "domain": "air", "confidence": 0.6},
        {"corridor_id": "sj_corridor", "domain": "context", "confidence": 0.9},
    ])

    assert len(baselines) == 2
    air = index_baselines(baselines)[("sj_corridor", "air")]
    assert air["historical_count"] == 2
    assert air["mean_confidence"] == 0.7
    assert air["operator_use"] == "review_context_only"
    assert air["live_tracking"] is False


def test_score_against_historical_baselines_emits_review_only_anomalies():
    current = [
        {"corridor_id": "sj_corridor", "domain": "air", "event_count": 4, "confidence": 0.9},
        {"corridor_id": "ponce_corridor", "domain": "context", "event_count": 1, "confidence": 0.1},
    ]
    historical = [
        {"corridor_id": "sj_corridor", "domain": "air", "historical_count": 2},
        {"corridor_id": "ponce_corridor", "domain": "context", "historical_count": 1},
    ]

    anomalies = score_against_historical_baselines(current, historical)

    assert len(anomalies) == 1
    assert anomalies[0]["corridor_id"] == "sj_corridor"
    assert anomalies[0]["review_band"] in {"moderate_review", "high_review"}
    assert anomalies[0]["operator_action"] == "review_context_only"
    assert anomalies[0]["live_tracking"] is False
    assert anomalies[0]["operational_cueing"] is False


def test_thehub_export_preserves_context_only_contract():
    payload = build_thehub_export(
        {"anomaly_count": 2},
        {"dashboard": "sensor_fusion_context", "metrics": {"overlap_count": 3}, "review_bands": {"high_review": 1}},
    )

    assert payload["producer"] == "skywatcher-pr"
    assert payload["consumer"] == "thehub-pr"
    assert payload["export_contract"] == "sensor_fusion_analytics_v1"
    assert payload["live_tracking"] is False
    assert payload["operational_cueing"] is False
    assert payload["operator_action"] == "review_context_only"
    assert payload["guardrails"] == {
        "context_only": True,
        "public_live_tracking": False,
        "operational_cueing": False,
    }


def test_visualization_payload_counts_review_bands_and_corridors():
    payload = build_visualization_payload({
        "anomalies": [
            {"review_band": "high_review", "corridor_id": "sj_corridor"},
            {"review_band": "high_review", "corridor_id": "sj_corridor"},
            {"review_band": "moderate_review", "corridor_id": "ponce_corridor"},
        ]
    })

    assert payload["dashboard"] == "sensor_fusion_analytics"
    assert payload["live_tracking"] is False
    assert payload["operator_action"] == "review_context_only"
    assert payload["charts"]["review_bands"] == [
        {"band": "high_review", "count": 2},
        {"band": "moderate_review", "count": 1},
    ]
    assert payload["charts"]["corridor_counts"] == [
        {"corridor_id": "ponce_corridor", "count": 1},
        {"corridor_id": "sj_corridor", "count": 2},
    ]
