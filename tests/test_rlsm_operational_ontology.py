from pathlib import Path

from pipeline.normalize_locations import load_simple_yaml, normalize_location
from pipeline.normalize_missions import normalize_blackout, normalize_mission
from pipeline.normalize_operators import normalize_aircraft_identity, normalize_operator
from pipeline.rlsm_ontology_gate import run_gate

CONFIG_DIR = Path("configs")


def test_airport_alias_resolution():
    for value in ["SJU", "TJSJ", "Luis Munoz Marin", "Isla Grande", "BQN"]:
        assert normalize_location(value, CONFIG_DIR)["normalized_id"] is not None


def test_na_identity_policy():
    for raw in ["N/A", "NA", "N A", "Unknown", "blocked", "no callsign"]:
        record = normalize_aircraft_identity(raw, "B407")
        assert record["identity_status"] == "masked_or_unresolved"
        assert record["tail_canonical"] is None
        assert record["merge_policy"] == "do_not_merge_without_cluster_evidence"


def test_operator_alias_resolution():
    record = normalize_operator("USCG", CONFIG_DIR)
    assert record["resolution_status"] == "resolved"
    assert record["operator_id"] == "op_uscg_cluster"


def test_mission_alias_resolution():
    assert normalize_mission("grid inspection", CONFIG_DIR)["mission_canonical"] == "UTILITY_INSPECTION"
    assert normalize_mission("coastal patrol", CONFIG_DIR)["mission_canonical"] == "MARITIME_PATROL"
    assert normalize_mission("private charter", CONFIG_DIR)["mission_canonical"] == "PRIVATE_CHARTER"


def test_gap_terms_preserve_uncertainty():
    # `UNKNOWN` is the CANONICAL class for ambiguous gap terms per
    # configs/blackout_vocab.yaml — "track gap" / "ADS-B loss" / "signal loss" /
    # "missing segment" / "fragment" all resolve here on purpose. The test name
    # captures the design intent: preserve uncertainty by classifying as UNKNOWN
    # rather than guessing TECHNICAL / SUSPICIOUS_CONTEXTUAL / LANDING_CANDIDATE.
    # Bug-fixed at rebase (2026-06-02): the original assertion was inverted
    # (`!= "UNKNOWN"`), which contradicted both the vocab and the test name.
    record = normalize_blackout("track gap", CONFIG_DIR)
    assert record["blackout_class"] == "UNKNOWN"
    assert record["resolution_status"] == "resolved"
    assert record["do_not_assume_intentional"] is True


def test_endpoint_visual_track_color_is_candidate_only():
    config = load_simple_yaml(CONFIG_DIR / "endpoint_recall_audit.yaml")
    white_cue = config["visual_track_cues"]["WHITE_TRACK_LINE"]
    assert white_cue["allowed_endpoint_inference"] == "endpoint_candidate_only"
    rules = config["matching_rules"]
    assert rules["preserve_visual_track_color"] is True
    assert rules["do_not_assume_white_track_line_confirms_takeoff_or_landing"] is True
    assert "visual_track_color" in config["required_audit_fields"]
    assert "visual_track_cue" in config["required_audit_fields"]


def test_gate_passes():
    result = run_gate(CONFIG_DIR)
    assert result["status"] == "pass", result
    assert result["ocr_baseline_allowed"] is True
