from satim_road_end import (
    RoadEndClass,
    RoadEndLink,
    RoadEndObservation,
    RoadEndSignal,
    VISIBLE_ACCESS_NODE_ONLY_STATUS,
    build_p_route_confidence_patch,
    build_road_end_node_ledger,
    road_end_schema,
    score_road_end_observation,
)


def road_end_fixture() -> RoadEndObservation:
    return RoadEndObservation(
        node_id="SATIM-ROAD-END-PR771-001",
        grid_id="PR-BARRANQUITAS-PR771-RIO_GRANDE_DE_MANATI",
        source_id="SATIM_PATCHWORK_POI_LEDGER:SATIM-PR771-BARRANQUITAS-001",
        timestamp_local="2026-06-29T15:00:00-04:00",
        signals={
            RoadEndSignal.DEAD_END: 1.0,
            RoadEndSignal.BULB_LOOP: 0.8,
            RoadEndSignal.WIDENED_SERVICE_PAD: 1.0,
            RoadEndSignal.PULL_OFF: 0.5,
            RoadEndSignal.SWITCHBACK_TERMINUS: 0.0,
        },
        classes=(
            RoadEndClass.ACCESS_NODE,
            RoadEndClass.MAINTENANCE_TURNAROUND,
            RoadEndClass.STAGING_PAD,
        ),
        links={
            RoadEndLink.PATCHWORK_POI: True,
            RoadEndLink.FR24_ROUTE_PROXIMITY: True,
            RoadEndLink.ADS_B_GAP: False,
            RoadEndLink.REPEAT_GRIDID: True,
        },
        patchwork_poi_id="SATIM-PR771-BARRANQUITAS-001",
        notes="Regression fixture linked to maintained patchwork clearing detector output.",
    )


def test_schema_contains_required_signals_and_guardrail():
    schema = road_end_schema()

    assert schema["detector"] == "SATIM_ROAD_END_TURNAROUND_DETECTOR_v1"
    assert schema["guardrail"] == VISIBLE_ACCESS_NODE_ONLY_STATUS
    assert "DEAD_END" in schema["signals"]
    assert "BULB_LOOP" in schema["signals"]
    assert "WIDENED_SERVICE_PAD" in schema["signals"]
    assert "PULL_OFF" in schema["signals"]
    assert "SWITCHBACK_TERMINUS" in schema["signals"]
    assert "ACCESS_NODE" in schema["classes"]


def test_fixture_scores_visible_geometry_and_links_separately():
    score = score_road_end_observation(road_end_fixture())

    assert score.visible_geometry_score == 0.725
    assert score.linkage_score == 0.3
    assert score.combined_score == 1.0
    assert score.confidence_band == "HIGH"
    assert score.access_status == VISIBLE_ACCESS_NODE_ONLY_STATUS
    assert score.visible_access_only_guardrail is True
    assert score.linked_evidence == (
        "FR24_ROUTE_PROXIMITY",
        "PATCHWORK_POI",
        "REPEAT_GRIDID",
    )


def test_node_ledger_retains_visible_access_guardrail():
    rows = build_road_end_node_ledger([road_end_fixture()])

    assert len(rows) == 1
    row = rows[0]
    assert row["node_id"] == "SATIM-ROAD-END-PR771-001"
    assert row["access_status"] == VISIBLE_ACCESS_NODE_ONLY_STATUS
    assert row["visible_access_only_guardrail"] is True
    assert row["signal_contributions"]["WIDENED_SERVICE_PAD"] == 0.25
    assert row["patchwork_poi_id"] == "SATIM-PR771-BARRANQUITAS-001"
    assert "STAGING_PAD" in row["classes"]


def test_p_route_confidence_patch_preserves_score_provenance():
    rows = build_p_route_confidence_patch([road_end_fixture()])

    assert len(rows) == 1
    row = rows[0]
    assert row["visible_geometry_score"] == 0.725
    assert row["linkage_score"] == 0.3
    assert row["provenance_rule"] == "visible_geometry_score and linkage_score remain separable"
    assert row["guardrail_status"] == VISIBLE_ACCESS_NODE_ONLY_STATUS
