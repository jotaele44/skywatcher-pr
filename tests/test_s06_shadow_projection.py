from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from skywatcher.ai_imagery.shadow_projection import *

S = "a" * 64
P = "b" * 64
R = "c" * 64


def campaign():
    return {"campaign_id": "dual-run-campaign-sha256-" + S, "source_set_sha256": S, "pins_sha256": P, "source_artifacts": [{"artifact_id": "artifact-sha256-" + S, "sha256": S}], "required_deterministic_outputs": ["manifest"]}


def fields():
    return [{"field_key": "registration", "value": "N123", "review_status": "REVIEWED", "provenance": {"source_artifact_id": "artifact-sha256-" + S, "source_sha256": S, "provider_id": "legacy-provider", "model_id": "legacy-model", "model_revision": "r1", "prompt_template_hash": P, "policy_version": "p1", "access_context_hash": R, "extraction_schema_version": "v1"}}]


def engine():
    return {"engine_id": "fr24_vision_ingest", "engine_revision": "legacy-v1", "provider_id": "legacy-provider", "model_id": "legacy-model", "model_revision": "r1", "prompt_template_hash": P, "policy_version": "p1", "access_context_hash": R, "extraction_schema_version": "v1"}


def legacy_export():
    return build_legacy_shadow_export(campaign_id=campaign()["campaign_id"], trial_id="trial-01", source_set_sha256=S, pins_sha256=P, skywatcher_revision=S05_REVISION, execution_receipt_sha256=R, legacy_engine=engine(), source_artifacts=campaign()["source_artifacts"], deterministic_outputs=[{"output_id": "manifest", "normalized_sha256": R}], model_fields=fields(), legacy_csv_text="registration,callsign\nN123,TEST\n", created_at="2026-08-09T12:00:00Z")


def test_identity_and_order():
    assert legacy_export() == legacy_export()


def test_csv_preserved():
    assert legacy_export()["legacy_artifacts"]["csv_rows"][0] == {"registration": "N123", "callsign": "TEST"}


def test_missing_provenance_denied():
    f = fields(); del f[0]["provenance"]["model_revision"]
    with pytest.raises(ShadowProjectionError):
        build_legacy_shadow_export(campaign_id=campaign()["campaign_id"], trial_id="t", source_set_sha256=S, pins_sha256=P, skywatcher_revision=S05_REVISION, execution_receipt_sha256=R, legacy_engine=engine(), source_artifacts=campaign()["source_artifacts"], deterministic_outputs=[{"output_id": "manifest", "normalized_sha256": R}], model_fields=f, legacy_csv_text="x\ny\n", created_at="2026-08-09T12:00:00Z")


def test_paths_and_secrets_denied():
    with pytest.raises(ShadowProjectionError): normalize_checkpoint(["/tmp/x"])
    e = engine(); e["api_key"] = "x"
    with pytest.raises(ShadowProjectionError):
        build_legacy_shadow_export(campaign_id=campaign()["campaign_id"], trial_id="t", source_set_sha256=S, pins_sha256=P, skywatcher_revision=S05_REVISION, execution_receipt_sha256=R, legacy_engine=e, source_artifacts=campaign()["source_artifacts"], deterministic_outputs=[{"output_id": "manifest", "normalized_sha256": R}], model_fields=fields(), legacy_csv_text="x\ny\n", created_at="2026-08-09T12:00:00Z")


def test_legacy_lane_h08_shape():
    lane = build_legacy_lane_projection_input(campaign(), legacy_export(), run_id="d" * 32, receipt_sha256=R, created_at="2026-08-09T12:00:00Z")
    assert lane["lane"] == "LEGACY_SHADOW" and lane["answer_eligible"] is False


def test_candidate_projection_and_required_refs():
    pkg = {"package_id": "pkg", "accounting": {"inputs": 1, "outputs": 1, "excluded": 0, "failed": 0}}
    lane = build_candidate_lane_projection_input(campaign(), trial_id="trial-01", run_id="e" * 32, receipt_sha256=R, h06_job_record_id="h06", h07_admission_receipt_id="h07", producer_package=pkg, collections={"source_artifacts": campaign()["source_artifacts"]}, model_fields=fields(), deterministic_outputs=[{"output_id": "manifest", "normalized_sha256": R}], created_at="2026-08-09T12:00:00Z")
    assert lane["lane"] == "ADR0006_CANDIDATE"
    with pytest.raises(ShadowProjectionError):
        build_candidate_lane_projection_input(campaign(), trial_id="t", run_id="e" * 32, receipt_sha256=R, h06_job_record_id="", h07_admission_receipt_id="h07", producer_package={}, collections={"source_artifacts": []}, model_fields=[], deterministic_outputs=[], created_at="2026-08-09T12:00:00Z")


def test_staging_manifest_relative_and_reproducible():
    assert build_staging_manifest({"trial/a.json": b"{}\n"}) == build_staging_manifest({"trial/a.json": b"{}\n"})
    with pytest.raises(ShadowProjectionError): build_staging_manifest({"../x": b"x"})


def test_static_boundary():
    source = (Path(__file__).parents[1] / "src/skywatcher/ai_imagery/shadow_projection.py").read_text().lower()
    for forbidden in ("import requests", "import urllib", "import socket", "import anthropic", "import openai", "import sqlite3", "subprocess", "os.environ"):
        assert forbidden not in source
