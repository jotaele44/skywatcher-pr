"""PITIRRE-C002 regression firewall for active mission/intent inference."""

from __future__ import annotations

import json
from pathlib import Path

from skywatcher.fpim import aircraft_profile
from skywatcher.fr24 import spiderweb_export


ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_active_ontology_keeps_mission_inference_unauthorized():
    manifest = json.loads(
        _text("docs/architecture/SKYWATCHER_ONTOLOGY_FREEZE_MANIFEST_v2_0.json")
    )
    assert manifest["mission_or_intent_inference_authorized"] is False


def test_fpim_deduced_profile_does_not_consume_legacy_type_mission_table():
    source = Path(aircraft_profile.__file__).read_text(encoding="utf-8")
    deduce = source.split("def _deduce_profile", 1)[1].split("def _enrich_from_db", 1)[0]
    assert "AIRCRAFT_TYPE_MISSIONS.items()" not in deduce
    assert "primary_mission = mission" not in deduce


def test_federation_export_never_promotes_legacy_mission_fields():
    source = Path(spiderweb_export.__file__).read_text(encoding="utf-8")
    assert "mc.classify" not in source
    record = spiderweb_export.build_bridge_record(
        {
            "flight_id": "FIREWALL",
            "mission_type": "legacy-inference",
            "mission_confidence": 1.0,
            "confidence": 0.5,
            "review_status": "promoted",
        },
        [],
        export_id="pkg_" + "a" * 32,
        source_snapshot_id="snapshot",
        generated_at_utc="2026-10-04T00:00:00Z",
    )
    assert record["mission_classification"] is None


def test_corrim_ilap_does_not_export_mission_type():
    source = _text("src/skywatcher/corrim/ilap_airspace_bridge.py")
    assert '"mission_type": f.get(' not in source


def test_evidence_registry_marks_mission_capabilities_prohibited():
    registry = json.loads(_text("config/evidence_skill_registry.json"))
    assert "mission_classification" in registry["prohibited_capabilities"]
    assert "mission_inference" in registry["prohibited_capabilities"]
    assert "intent_inference" in registry["prohibited_capabilities"]
    for skill in registry.get("skills", []):
        assert "mission_classification" not in skill.get("capabilities", [])


def test_canonical_frontend_has_no_mission_inference_field():
    offenders = []
    for path in (ROOT / "frontend" / "src").rglob("*"):
        if path.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            continue
        if "mission_inference" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_aircraft_ui_labels_authoritative_mission_as_declared():
    aircraft_page = _text("frontend/src/pages/Aircraft.jsx")
    aircraft_card = _text("frontend/src/components/skywatcher/AircraftProfileCard.jsx")
    aircraft_drawer = _text(
        "frontend/src/components/skywatcher/drawers/AircraftDetailDrawer.jsx"
    )
    assert "Declared Mission" in aircraft_page
    assert "Declared:" in aircraft_card
    assert "Source-declared Mission" in aircraft_drawer


def test_rlsm_extraction_readiness_has_no_mission_vocab_dependency():
    ontology = _text("configs/rlsm_operational_ontology.yaml")
    assert "configs/mission_vocab.yaml" not in ontology
    assert "mission_or_intent_inference_prohibited: true" in ontology
