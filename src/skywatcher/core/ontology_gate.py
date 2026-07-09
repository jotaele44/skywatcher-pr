#!/usr/bin/env python3
"""Gate OCR baseline runs on RLSM ontology readiness.

This script fails closed when required registry files are missing or common aliases fail resolution.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

from skywatcher.core.normalize_locations import load_simple_yaml, normalize_location
from skywatcher.core.normalize_missions import normalize_mission, normalize_blackout
from skywatcher.core.normalize_operators import normalize_aircraft_identity, normalize_operator

REQUIRED_CONFIGS = [
    "place_aliases.yaml",
    "airport_registry.yaml",
    "hangar_registry.yaml",
    "lz_registry.yaml",
    "poi_registry.yaml",
    "operator_registry.yaml",
    "facility_operator_registry.yaml",
    "aircraft_aliases.yaml",
    "mission_vocab.yaml",
    "behavior_vocab.yaml",
    # Renamed at rebase time (2026-06-02). See pipeline/normalize_locations.py
    # comment — main's `configs/corridor_registry.yaml` is the observed catalog;
    # the ontology layer reads canonical-name + aliases from corridor_aliases.yaml.
    "corridor_aliases.yaml",
    "blackout_vocab.yaml",
    "access_status_vocab.yaml",
    "spiderweb_terms.yaml",
    "location_naming_guardrails.yaml",
    "endpoint_recall_audit.yaml",
]


def run_gate(config_dir: Path = Path("configs")) -> Dict[str, object]:
    failures: List[str] = []
    warnings: List[str] = []

    for filename in REQUIRED_CONFIGS:
        if not (config_dir / filename).exists():
            failures.append(f"missing required config: {filename}")

    guardrail_path = config_dir / "location_naming_guardrails.yaml"
    if guardrail_path.exists():
        guardrails = load_simple_yaml(guardrail_path)
        principles = guardrails.get("principles", {}) or {}
        for required_rule in [
            "preserve_raw_label",
            "never_invent_site_names",
            "separate_visible_label_from_project_name",
            "require_review_for_unlabeled_locations",
        ]:
            if principles.get(required_rule) is not True:
                failures.append(f"location naming guardrail missing or false: {required_rule}")

    facility_operator_path = config_dir / "facility_operator_registry.yaml"
    if facility_operator_path.exists():
        facility_ops = load_simple_yaml(facility_operator_path)
        rules = facility_ops.get("rules", {}) or {}
        for required_rule in [
            "preserve_visible_operator_label",
            "preserve_unlabeled_operator_as_unresolved",
            "do_not_convert_context_operator_to_verified",
            "separate_facility_operator_from_aircraft_operator",
        ]:
            if rules.get(required_rule) is not True:
                failures.append(f"facility operator rule missing or false: {required_rule}")

    endpoint_audit_path = config_dir / "endpoint_recall_audit.yaml"
    if endpoint_audit_path.exists():
        endpoint_audit = load_simple_yaml(endpoint_audit_path)
        visual_cues = endpoint_audit.get("visual_track_cues", {}) or {}
        white_cue = visual_cues.get("WHITE_TRACK_LINE", {}) or {}
        if white_cue.get("allowed_endpoint_inference") != "endpoint_candidate_only":
            failures.append("white track line must be candidate-only")
        required_fields = endpoint_audit.get("required_audit_fields", []) or []
        for required_field in ["visual_track_color", "visual_track_cue"]:
            if required_field not in required_fields:
                failures.append(f"endpoint audit field missing: {required_field}")
        rules = endpoint_audit.get("matching_rules", {}) or {}
        for required_rule in [
            "preserve_visual_track_color",
            "audit_takeoff_and_landing_separately",
            "do_not_assume_white_track_line_confirms_takeoff_or_landing",
            "do_not_assume_track_start_equals_takeoff",
            "do_not_assume_track_end_equals_landing",
            "route_unlogged_endpoints_to_review",
            "create_project_location_id_for_new_unlogged_endpoint",
        ]:
            if rules.get(required_rule) is not True:
                failures.append(f"endpoint recall audit rule missing or false: {required_rule}")

    alias_expectations = {
        "SJU": {"resolved"},
        "TJSJ": {"resolved"},
        "Luis Munoz Marin": {"resolved"},
        "SIG": {"resolved"},
        "Isla Grande": {"resolved"},
        "BQN": {"resolved"},
        # Ramey is intentionally ambiguous: airport, former-base complex, and Borinquen operational area.
        "Ramey": {"resolved", "collision_review_required"},
        "Vieques airport": {"resolved"},
    }
    for raw, expected_statuses in alias_expectations.items():
        resolved = normalize_location(raw, config_dir=config_dir)
        if resolved.get("resolution_status") not in expected_statuses:
            failures.append(f"alias resolution failed: {raw} -> {resolved}")

    for raw in ["N/A", "Unknown", "blocked"]:
        ident = normalize_aircraft_identity(raw)
        if ident.get("identity_status") != "masked_or_unresolved":
            failures.append(f"masked aircraft handling failed: {raw} -> {ident}")
        if ident.get("merge_policy") != "do_not_merge_without_cluster_evidence":
            failures.append(f"masked aircraft merge policy missing: {raw}")

    for raw in ["grid inspection", "coastal patrol", "private charter"]:
        mission = normalize_mission(raw, config_dir=config_dir)
        if mission.get("mission_canonical") == "UNKNOWN":
            failures.append(f"mission alias failed: {raw} -> {mission}")

    operator = normalize_operator("USCG", config_dir=config_dir)
    if operator.get("resolution_status") != "resolved":
        failures.append(f"operator alias failed: USCG -> {operator}")

    blackout = normalize_blackout("track gap", config_dir=config_dir)
    # `UNKNOWN` is a CANONICAL blackout class per configs/blackout_vocab.yaml —
    # it means "we know there's a gap, but the cause isn't determined" (intentional
    # uncertainty preservation). The gate must check whether resolution SUCCEEDED,
    # not whether the class happens to be named UNKNOWN. Bug-fixed at rebase
    # (2026-06-02): the original `== "UNKNOWN"` check rejected the very semantic
    # the vocab is designed to preserve.
    if blackout.get("resolution_status") != "resolved":
        failures.append(f"blackout alias failed: track gap -> {blackout}")
    if not blackout.get("do_not_assume_intentional"):
        failures.append("blackout intent guard missing")

    status = "pass" if not failures else "fail"
    return {
        "gate": "rlsm_operational_ontology_v0_1",
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "ocr_baseline_allowed": status == "pass",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", default="configs")
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    result = run_gate(Path(args.config_dir))
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
