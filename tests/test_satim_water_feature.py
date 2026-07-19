from satim_water_feature import (
    NON_DESTRUCTIVE_ARTIFACT_FILTER,
    VISIBLE_SURFACE_HYDROLOGY_ONLY,
    WaterClass,
    WaterLink,
    WaterObservation,
    WaterSignal,
    build_hydrology_context_layer,
    build_p_route_confidence_patch,
    build_water_feature_ledger,
    score_water_observation,
    water_feature_schema,
)


def fixture(kind: str) -> WaterObservation:
    common = dict(
        feature_id=f"WATER-{kind.upper()}",
        grid_id="PR-HYDRO-GRID-001",
        source_id="SATIM:synthetic",
        timestamp_local="2026-07-19T12:00:00-04:00",
        links={
            WaterLink.PATCHWORK_POI: True,
            WaterLink.ROAD_END_NODE: True,
            WaterLink.CUT_FILL_FEATURE: True,
            WaterLink.LINEAR_CORRIDOR: True,
            WaterLink.REPEAT_GRIDID: True,
        },
        patchwork_poi_id="PATCH-001",
        road_end_node_id="ROAD-001",
        cut_fill_feature_id="CUT-001",
        linear_corridor_id="LINEAR-001",
        repeat_grid_id="PR-HYDRO-GRID-001",
        notes="Synthetic regression fixture; visible surface hydrology only.",
    )
    base = {
        WaterSignal.WATER_SURFACE_VISIBILITY: 0.95,
        WaterSignal.SHORELINE_CONTINUITY: 0.85,
        WaterSignal.BASIN_GEOMETRY: 0.75,
        WaterSignal.VEGETATION_MOISTURE_CONTRAST: 0.7,
        WaterSignal.RECURRENCE: 0.8,
    }
    if kind == "natural":
        return WaterObservation(
            **common,
            signals={**base, WaterSignal.PERMANENT_POND: 1.0},
            classes=(WaterClass.NATURAL_WATER,),
            artifact_confidence=0.05,
        )
    if kind == "retention":
        return WaterObservation(
            **common,
            signals={
                **base,
                WaterSignal.RETENTION_BASIN: 1.0,
                WaterSignal.BERM: 0.9,
                WaterSignal.BERM_CONTINUITY: 0.9,
                WaterSignal.DRAINAGE_OUTLET: 0.8,
            },
            classes=(WaterClass.ARTIFICIAL_RETENTION,),
            artifact_confidence=0.1,
        )
    if kind == "agricultural":
        return WaterObservation(
            **common,
            signals={
                **base,
                WaterSignal.PERMANENT_POND: 0.8,
                WaterSignal.BERM: 0.8,
                WaterSignal.INLET_OUTLET_VISIBILITY: 0.7,
            },
            classes=(WaterClass.AGRICULTURAL_RESERVOIR,),
            artifact_confidence=0.1,
        )
    if kind == "quarry":
        return WaterObservation(
            **common,
            signals={
                **base,
                WaterSignal.EXCAVATED_WATER_BODY: 1.0,
                WaterSignal.EXCAVATION_EVIDENCE: 1.0,
            },
            classes=(WaterClass.QUARRY_WATER,),
            artifact_confidence=0.15,
        )
    if kind == "stormwater":
        return WaterObservation(
            **common,
            signals={
                **base,
                WaterSignal.DETENTION_BASIN: 1.0,
                WaterSignal.SPILLWAY: 0.9,
                WaterSignal.SPILLWAY_EVIDENCE: 0.9,
                WaterSignal.DRAINAGE_OUTLET: 0.9,
            },
            classes=(WaterClass.STORMWATER_FEATURE,),
            artifact_confidence=0.1,
        )
    if kind == "artifact_review":
        return WaterObservation(
            **common,
            signals={**base, WaterSignal.SEASONAL_WATER: 0.7},
            classes=(WaterClass.UNKNOWN_WATER,),
            artifact_confidence=0.9,
        )
    return WaterObservation(
        **common,
        signals={WaterSignal.WATER_SURFACE_VISIBILITY: 0.35},
        classes=(),
        artifact_confidence=0.2,
    )


def test_schema_contract_and_guardrails():
    schema = water_feature_schema()
    assert schema["detector"] == "SATIM_WATER_RETENTION_AND_POND_DETECTOR_v1"
    assert schema["guardrail"] == VISIBLE_SURFACE_HYDROLOGY_ONLY
    assert schema["artifact_filter"] == NON_DESTRUCTIVE_ARTIFACT_FILTER
    for required in (
        "PERMANENT_POND",
        "RETENTION_BASIN",
        "DETENTION_BASIN",
        "SEASONAL_WATER",
        "EXCAVATED_WATER_BODY",
        "SPILLWAY",
        "DRAINAGE_OUTLET",
        "BERM",
    ):
        assert required in schema["signals"]
    assert set(schema["signal_weights"]) == set(schema["signals"])
    assert "UNKNOWN_WATER" in schema["classes"]
    assert set(schema["links"]) == {item.value for item in WaterLink}


def test_all_required_fixture_classes_are_supported():
    expected = {
        "natural": "NATURAL_WATER",
        "retention": "ARTIFICIAL_RETENTION",
        "agricultural": "AGRICULTURAL_RESERVOIR",
        "quarry": "QUARRY_WATER",
        "stormwater": "STORMWATER_FEATURE",
        "unknown": "UNKNOWN_WATER",
    }
    for kind, class_name in expected.items():
        assert score_water_observation(fixture(kind)).classes == (class_name,)


def test_scoring_is_deterministic_bounded_and_auditable():
    source = fixture("retention")
    first = score_water_observation(source)
    second = score_water_observation(source)
    assert first == second
    assert 0.0 <= first.original_detector_score <= 1.0
    assert 0.0 <= first.adjusted_detector_score <= 1.0
    assert first.pre_filter_score >= first.original_detector_score
    assert first.adjusted_detector_score <= first.pre_filter_score
    row = build_water_feature_ledger([source])[0]
    assert set(row["signal_contributions"]) == {item.value for item in WaterSignal}
    assert row["guardrail"] == VISIBLE_SURFACE_HYDROLOGY_ONLY


def test_artifact_filter_is_non_destructive_and_separable():
    source = fixture("artifact_review")
    score = score_water_observation(source)
    assert score.artifact_filter_status == NON_DESTRUCTIVE_ARTIFACT_FILTER
    assert score.original_detector_score > score.adjusted_detector_score
    assert score.review_required is True
    assert "HIGH_ARTIFACT_CONFIDENCE" in score.review_reasons
    patch = build_p_route_confidence_patch([source])[0]
    assert patch["mutation_rule"] == "candidate retained; emit confidence patch only"
    assert patch["original_detector_score"] != patch["adjusted_detector_score"]


def test_links_and_context_layer_are_preserved():
    source = fixture("quarry")
    row = build_water_feature_ledger([source])[0]
    assert row["linked_evidence"] == sorted(item.value for item in WaterLink)
    assert row["cut_fill_feature_id"] == "CUT-001"
    context = build_hydrology_context_layer([source])[0]
    assert context["feature_id"] == source.feature_id
    assert context["guardrail"] == VISIBLE_SURFACE_HYDROLOGY_ONLY
    assert "no purpose or ownership inference" in context["context_rule"]


def test_unknown_and_missing_optional_evidence_do_not_drop_candidate():
    source = fixture("unknown")
    ledger = build_water_feature_ledger([source])
    patch = build_p_route_confidence_patch([source])
    assert len(ledger) == 1
    assert len(patch) == 1
    assert ledger[0]["classes"] == ["UNKNOWN_WATER"]
    assert ledger[0]["review_required"] is True
