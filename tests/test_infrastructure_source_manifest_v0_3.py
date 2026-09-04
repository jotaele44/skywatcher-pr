from __future__ import annotations

import json
from pathlib import Path

import pytest

from skywatcher.corrim.infrastructure_source_manifest import (
    AdmissionState,
    ManifestError,
    coordinate_collision_groups,
    iter_features,
    load_manifest,
    require_production_admission,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/infrastructure/legacy_infrastructure_source_manifest_v0_3.json"


def test_manifest_denominator_and_unique_ids_close():
    payload = load_manifest(MANIFEST)
    rows = list(iter_features(payload))
    assert len(rows) == 24
    assert len({row.feature_id for row in rows}) == 24


def test_all_legacy_rows_are_audit_only_candidates():
    payload = load_manifest(MANIFEST)
    rows = list(iter_features(payload))
    assert all(row.identity_semantics == "CANDIDATE_NOT_IDENTITY" for row in rows)
    assert all(row.certification_state == "AUDIT_ONLY" for row in rows)
    assert all(row.production_admitted is False for row in rows)


def test_manifest_proves_exact_legacy_code_manifestation():
    payload = load_manifest(MANIFEST)
    assert payload["producer_source_head"] == "6b95f816f1dc2c2081734df582920703743fbdf3"
    assert payload["legacy_source"]["git_blob_sha1"] == "5650253d6641678e61a54044de282b6fdae3587e"
    assert payload["legacy_source"]["source_manifestation_identity"] == "CODE_LITERAL_AT_EXACT_GIT_BLOB"


def test_production_admission_fails_closed():
    payload = load_manifest(MANIFEST)
    with pytest.raises(ManifestError, match="AUDIT_ONLY"):
        require_production_admission(payload)


def test_nonproduction_state_remains_audit_only():
    payload = load_manifest(MANIFEST)
    from skywatcher.corrim.infrastructure_source_manifest import admission_state
    assert admission_state(payload, production=False) is AdmissionState.AUDIT_ONLY
    assert admission_state(payload, production=True) is AdmissionState.BLOCKED


def test_sig_legacy_classification_is_explicitly_superseded():
    payload = load_manifest(MANIFEST)
    sig = next(row for row in payload["features"] if row["feature_id"] == "SIG")
    assert sig["legacy_type"] == "heliport"
    assert sig["migration_state"].startswith("SUPERSEDED_CLASSIFICATION_AIRPORT_ENTITY_TJIG")


def test_coordinate_collisions_are_preserved_not_collapsed():
    payload = load_manifest(MANIFEST)
    groups = coordinate_collision_groups(payload)
    assert set(groups[(18.4386, -66.001)]) == {"SJU", "USCG_SJ", "CBP_SJ", "TISJ_TRACON"}
    assert set(groups[(18.5049, -67.1314)]) == {"BQN", "CBP_AMO_BQN"}
    assert set(groups[(18.4048, -66.0638)]) == {"FEMA_CARIBBEAN", "USMS_SDPR"}


def test_every_row_has_candidate_authoritative_source_family():
    payload = load_manifest(MANIFEST)
    assert all(row["candidate_source_family"].strip() for row in payload["features"])


def test_validator_rejects_identity_promotion():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["row_defaults"]["identity_semantics"] = "IDENTITY_BINDING"
    with pytest.raises(ManifestError, match="candidate-not-identity"):
        validate_manifest(payload)


def test_validator_rejects_production_admission():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["row_defaults"]["production_admitted"] = True
    with pytest.raises(ManifestError, match="production-admitted"):
        validate_manifest(payload)


def test_validator_rejects_duplicate_ids():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["features"][1]["feature_id"] = payload["features"][0]["feature_id"]
    with pytest.raises(ManifestError, match="unique"):
        validate_manifest(payload)


def test_scope_preserves_all_24_exact_literals():
    payload = load_manifest(MANIFEST)
    expected = {
        "SJU","SIG","BQN","PSE","NRR","PREPA_SOUTH_CORRIDOR","PREPA_CENTRAL_GRID","PALO_SECO",
        "USCG_SJ","MONA_PASSAGE","PORT_SJ","RESTRICTED_VIEQUES","FURA_BASE_SJ","FBI_SJ",
        "CBP_SJ","FEMA_CARIBBEAN","CBP_AMO_BQN","USMS_SDPR","TJUA","TJBQ","TISJ_TRACON",
        "WINDWARD_PASSAGE","ANEGADA_PASSAGE","MONA_CHOKEPOINT"
    }
    assert {row["feature_id"] for row in payload["features"]} == expected


def test_exact_spiderweb_candidate_pin_is_immutable_and_blocked():
    pin = json.loads((ROOT / "federation/spiderweb_archipelago_release_pin_v0_3.json").read_text())
    assert pin["producer_commit_sha"] == "3440996569d977069f782a4755f686dfcab818ba"
    assert pin["source_snapshot_sha256"] == "6e8a29fc87178264584c5e88add8ac63d8e0e9a72b9f05f63795c6edec2c92e4"
    assert pin["admission"]["immutable_input_pin"] == "PASS"
    assert pin["admission"]["runtime_activation"] is False
    assert pin["admission"]["consumer_may_recompute_geometry"] is False
