from __future__ import annotations

from fr24_image_skill.adapters import capability_report, discover_capabilities


def test_adapter_registry_accounts_for_required_capabilities() -> None:
    capabilities = discover_capabilities()
    assert set(capabilities) == {
        "ui_segmenter",
        "region_ocr",
        "rlsm_ocr",
        "flight_fusion",
        "track_vectorizer",
        "affine_georegistration",
        "satim_engine",
        "tile_seam_classifier",
    }


def test_adapter_discovery_is_import_safe_and_serializable() -> None:
    report = capability_report()
    assert len(report) == 8
    assert all(set(row) == {"name", "module", "symbol", "available", "error"} for row in report)
    assert all(isinstance(row["available"], bool) for row in report)


def test_unavailable_adapters_report_errors_instead_of_synthetic_results() -> None:
    for capability in discover_capabilities().values():
        if not capability.available:
            assert capability.implementation is None
            assert capability.error
