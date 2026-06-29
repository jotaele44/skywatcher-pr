from satim_patchwork import (
    FlightLink,
    PatchworkClass,
    PatchworkObservation,
    PatchworkSignal,
    VISIBLE_SURFACE_ONLY_STATUS,
    build_p_route_confidence_patch,
    build_patchwork_poi_ledger,
    patchwork_schema,
    score_patchwork_observation,
)


def barranquitas_fixture() -> PatchworkObservation:
    return PatchworkObservation(
        poi_id="SATIM-PR771-BARRANQUITAS-001",
        grid_id="PR-BARRANQUITAS-PR771-RIO_GRANDE_DE_MANATI",
        source_id="FR24_SCREENSHOT_2026-06-29_1500_AST_FRAMESET",
        timestamp_local="2026-06-29T15:00:00-04:00",
        signals={
            PatchworkSignal.LOW_CANOPY_MANAGED_SURFACE: 1.0,
            PatchworkSignal.DIRT_SERVICE_ROAD_NETWORK: 1.0,
            PatchworkSignal.PATCH_BOUNDARY_GEOMETRY: 1.0,
            PatchworkSignal.ROAD_END_TURNAROUND: 0.8,
            PatchworkSignal.CUT_FILL_EXPOSURE: 1.0,
            PatchworkSignal.INFRASTRUCTURE_ADJACENCY: 1.0,
        },
        classes=(
            PatchworkClass.QUARRY_OR_BORROW_PIT,
            PatchworkClass.RECREATIONAL_MUNICIPAL_EDGE,
        ),
        flight_links={
            FlightLink.FR24_ROUTE_PROXIMITY: True,
            FlightLink.ADS_B_GAP: False,
            FlightLink.LOITER_HOVER: False,
            FlightLink.REPEAT_GRIDID: True,
        },
        notes="Barranquitas / PR-771 / Río Grande de Manatí maintained patchwork clearing fixture.",
    )


def test_patchwork_schema_contains_required_signals_and_guardrail():
    schema = patchwork_schema()

    assert schema["detector"] == "SATIM_MAINTAINED_PATCHWORK_CLEARING_DETECTOR_v1"
    assert schema["guardrail"] == VISIBLE_SURFACE_ONLY_STATUS
    assert "LOW_CANOPY_MANAGED_SURFACE" in schema["signals"]
    assert "DIRT_SERVICE_ROAD_NETWORK" in schema["signals"]
    assert "ROAD_END_TURNAROUND" in schema["signals"]
    assert "CUT_FILL_EXPOSURE" in schema["signals"]
    assert "QUARRY_OR_BORROW_PIT" in schema["classes"]


def test_barranquitas_fixture_scores_visible_surface_and_links_separately():
    score = score_patchwork_observation(barranquitas_fixture())

    assert score.visual_surface_score == 0.97
    assert score.flight_link_score == 0.2
    assert score.combined_score == 1.0
    assert score.confidence_band == "HIGH"
    assert score.ilap_status == VISIBLE_SURFACE_ONLY_STATUS
    assert score.visible_surface_only_guardrail is True
    assert score.linked_route_evidence == ("FR24_ROUTE_PROXIMITY", "REPEAT_GRIDID")


def test_poi_ledger_retains_visible_surface_guardrail():
    rows = build_patchwork_poi_ledger([barranquitas_fixture()])

    assert len(rows) == 1
    row = rows[0]
    assert row["poi_id"] == "SATIM-PR771-BARRANQUITAS-001"
    assert row["ilap_status"] == VISIBLE_SURFACE_ONLY_STATUS
    assert row["visible_surface_only_guardrail"] is True
    assert row["signal_contributions"]["DIRT_SERVICE_ROAD_NETWORK"] == 0.25
    assert "QUARRY_OR_BORROW_PIT" in row["classes"]


def test_p_route_confidence_patch_preserves_score_provenance():
    rows = build_p_route_confidence_patch([barranquitas_fixture()])

    assert len(rows) == 1
    row = rows[0]
    assert row["visual_surface_score"] == 0.97
    assert row["flight_link_score"] == 0.2
    assert row["provenance_rule"] == "visual_surface_score and flight_link_score remain separable"
    assert row["guardrail_status"] == VISIBLE_SURFACE_ONLY_STATUS
