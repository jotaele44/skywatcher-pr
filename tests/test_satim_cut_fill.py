from satim_cut_fill import (
    CutFillClass,
    CutFillLink,
    CutFillObservation,
    CutFillSignal,
    VISIBLE_EARTHWORK_ONLY_STATUS,
    build_cut_fill_ledger,
    build_p_route_confidence_patch,
    cut_fill_schema,
    score_cut_fill_observation,
)


def cut_fill_fixture() -> CutFillObservation:
    return CutFillObservation(
        feature_id="SATIM-CUT-FILL-PR771-001",
        grid_id="PR-BARRANQUITAS-PR771-RIO_GRANDE_DE_MANATI",
        source_id="SATIM_ROAD_END_NODE_LEDGER:SATIM-ROAD-END-PR771-001",
        timestamp_local="2026-06-29T15:00:00-04:00",
        signals={
            CutFillSignal.EXCAVATION_FACE: 1.0,
            CutFillSignal.GRADED_PAD: 1.0,
            CutFillSignal.SPOIL_PILE: 0.8,
            CutFillSignal.BORROW_PIT: 0.5,
            CutFillSignal.TERRACE_SCARP: 0.6,
            CutFillSignal.RETAINING_FILL: 0.4,
        },
        classes=(
            CutFillClass.QUARRY,
            CutFillClass.CONSTRUCTION_PAD,
            CutFillClass.UNKNOWN_EARTHWORK,
        ),
        links={
            CutFillLink.PATCHWORK_POI: True,
            CutFillLink.ROAD_END_NODE: True,
            CutFillLink.FR24_ROUTE_PROXIMITY: True,
            CutFillLink.ADS_B_GAP: False,
            CutFillLink.REPEAT_GRIDID: True,
        },
        patchwork_poi_id="SATIM-PR771-BARRANQUITAS-001",
        road_end_node_id="SATIM-ROAD-END-PR771-001",
        notes="Regression fixture linked to maintained patchwork and road-end detector outputs.",
    )


def test_schema_contains_required_signals_and_guardrail():
    schema = cut_fill_schema()

    assert schema["classifier"] == "SATIM_CUT_FILL_EXPOSURE_CLASSIFIER_v1"
    assert schema["guardrail"] == VISIBLE_EARTHWORK_ONLY_STATUS
    assert "EXCAVATION_FACE" in schema["signals"]
    assert "GRADED_PAD" in schema["signals"]
    assert "SPOIL_PILE" in schema["signals"]
    assert "BORROW_PIT" in schema["signals"]
    assert "TERRACE_SCARP" in schema["signals"]
    assert "RETAINING_FILL" in schema["signals"]
    assert "UNKNOWN_EARTHWORK" in schema["classes"]


def test_fixture_scores_visible_earthwork_and_links_separately():
    score = score_cut_fill_observation(cut_fill_fixture())

    assert score.visible_earthwork_score == 0.82
    assert score.linkage_score == 0.4
    assert score.combined_score == 1.0
    assert score.confidence_band == "HIGH"
    assert score.earthwork_status == VISIBLE_EARTHWORK_ONLY_STATUS
    assert score.visible_earthwork_only_guardrail is True
    assert score.linked_evidence == (
        "FR24_ROUTE_PROXIMITY",
        "PATCHWORK_POI",
        "REPEAT_GRIDID",
        "ROAD_END_NODE",
    )


def test_cut_fill_ledger_retains_visible_earthwork_guardrail():
    rows = build_cut_fill_ledger([cut_fill_fixture()])

    assert len(rows) == 1
    row = rows[0]
    assert row["feature_id"] == "SATIM-CUT-FILL-PR771-001"
    assert row["earthwork_status"] == VISIBLE_EARTHWORK_ONLY_STATUS
    assert row["visible_earthwork_only_guardrail"] is True
    assert row["signal_contributions"]["EXCAVATION_FACE"] == 0.25
    assert row["patchwork_poi_id"] == "SATIM-PR771-BARRANQUITAS-001"
    assert row["road_end_node_id"] == "SATIM-ROAD-END-PR771-001"
    assert "CONSTRUCTION_PAD" in row["classes"]


def test_p_route_confidence_patch_preserves_score_provenance():
    rows = build_p_route_confidence_patch([cut_fill_fixture()])

    assert len(rows) == 1
    row = rows[0]
    assert row["visible_earthwork_score"] == 0.82
    assert row["linkage_score"] == 0.4
    assert row["provenance_rule"] == "visible_earthwork_score and linkage_score remain separable"
    assert row["guardrail_status"] == VISIBLE_EARTHWORK_ONLY_STATUS
