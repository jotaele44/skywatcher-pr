#!/usr/bin/env python3
"""Run the canonical visual-reasoning decision layer in non-activating shadow mode.

Input is JSON or JSONL containing normalized observations. The runner never
writes production outputs and never mutates source records. It emits a
side-by-side ledger containing the supplied legacy/baseline state, canonical
state, reason codes, and a conservative change classification.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from skywatcher.satim.visual_reasoning_runtime import (
    ArtifactObservation,
    ExcavationObservation,
    LocationCandidate,
    MultiframeObservation,
    PalmObservation,
    ParameterSet,
    PortalObservation,
    QuarryObservation,
    RegisteredFeatureObservation,
    RegistrationMetrics,
    SeamObservation,
    ShadowObservation,
    WaterObservation,
    ZoomObservation,
    assess_artifact,
    assess_excavation,
    assess_multiframe,
    assess_multiscale,
    assess_palm,
    assess_portal,
    assess_quarry,
    assess_seam,
    assess_shadow,
    assess_water,
    assess_zoom,
    locate_scene,
)

SUPPORTED_KINDS = {
    "zoom",
    "shadow",
    "seam",
    "artifact",
    "palm",
    "water",
    "quarry",
    "excavation",
    "portal",
    "multiscale",
    "multiframe",
    "locator",
}

IDENTITY_LIKE_STATES = {
    "EXACT_CERTIFIED",
}
WEAK_EVIDENCE_REASONS = {
    "RC_DISCOVERY_NOT_IDENTITY",
    "RC_ONE_LABEL_NOT_EXACT",
    "RC_PROXIMITY_NOT_IDENTITY",
    "RC_ARTIFACT_EXCLUDED_FROM_LOCATOR",
    "RC_VISUAL_QUARRY_NOT_LEGAL_IDENTITY",
    "RC_PORTAL_NOT_UNDERGROUND_IDENTITY",
}


def _load_json_or_jsonl(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        payload = json.loads(text)
        if not isinstance(payload, list):
            raise ValueError("JSON array input must contain a list")
        return [dict(item) for item in payload]
    if text.startswith("{"):
        payload = json.loads(text)
        if isinstance(payload, dict) and isinstance(payload.get("records"), list):
            return [dict(item) for item in payload["records"]]
        if isinstance(payload, dict):
            return [dict(payload)]
        raise ValueError("JSON object input is unsupported")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _observation_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("observation")
    if not isinstance(payload, dict):
        raise ValueError("record.observation must be an object")
    return dict(payload)


def _dispatch(record: dict[str, Any], params: ParameterSet) -> dict[str, Any]:
    kind = str(record.get("kind", ""))
    if kind not in SUPPORTED_KINDS:
        raise ValueError(f"unsupported kind: {kind!r}")
    payload = _observation_payload(record)

    if kind == "zoom":
        result = assess_zoom(ZoomObservation(**payload), params)
    elif kind == "shadow":
        result = assess_shadow(ShadowObservation(**payload), params)
    elif kind == "seam":
        result = assess_seam(SeamObservation(**payload), params)
    elif kind == "artifact":
        result = assess_artifact(ArtifactObservation(**payload), params)
    elif kind == "palm":
        result = assess_palm(PalmObservation(**payload), params)
    elif kind == "water":
        result = assess_water(WaterObservation(**payload), params)
    elif kind == "quarry":
        result = assess_quarry(QuarryObservation(**payload), params)
    elif kind == "excavation":
        result = assess_excavation(ExcavationObservation(**payload), params)
    elif kind == "portal":
        result = assess_portal(PortalObservation(**payload), params)
    elif kind == "multiscale":
        result = assess_multiscale(RegisteredFeatureObservation(**payload), params)
    elif kind == "multiframe":
        result = assess_multiframe(MultiframeObservation(**payload), params)
    else:
        candidates_raw = payload.get("candidates")
        if not isinstance(candidates_raw, list):
            raise ValueError("locator observation.candidates must be a list")
        candidates = [LocationCandidate(**dict(item)) for item in candidates_raw]
        registration_raw = payload.get("registration")
        registration = (
            RegistrationMetrics(**dict(registration_raw))
            if isinstance(registration_raw, dict)
            else None
        )
        result = locate_scene(candidates, params, registration)

    return asdict(result)


def _change_class(baseline_state: str | None, canonical_state: str) -> str:
    if baseline_state is None:
        return "NO_BASELINE_STATE"
    if baseline_state == canonical_state:
        return "UNCHANGED"
    if canonical_state in {"UNRESOLVED", "MULTIPLE_CANDIDATES", "AMBIGUOUS"}:
        return "CANONICAL_MORE_CONSERVATIVE"
    if baseline_state in {"UNRESOLVED", "MULTIPLE_CANDIDATES", "AMBIGUOUS"}:
        return "CANONICAL_PROMOTION_REQUIRES_REVIEW"
    return "STATE_CHANGED_REQUIRES_REVIEW"


def run_shadow_mode(
    records: list[dict[str, Any]],
    parameters: dict[str, float],
) -> dict[str, Any]:
    params = ParameterSet(parameters)
    rows: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    for index, record in enumerate(records):
        result = _dispatch(record, params)
        canonical_state = str(result["state"])
        reasons = tuple(str(value) for value in result.get("reason_codes", ()))
        baseline_state_raw = record.get("baseline_state")
        baseline_state = str(baseline_state_raw) if baseline_state_raw is not None else None
        source_id = str(record.get("source_id", f"row-{index}"))
        row = {
            "source_id": source_id,
            "kind": record["kind"],
            "baseline_state": baseline_state,
            "canonical_state": canonical_state,
            "change_class": _change_class(baseline_state, canonical_state),
            "reason_codes": list(reasons),
            "canonical_result": result,
            "production_activated": False,
        }
        rows.append(row)

        if canonical_state in IDENTITY_LIKE_STATES and any(
            reason in WEAK_EVIDENCE_REASONS for reason in reasons
        ):
            violations.append(
                {
                    "source_id": source_id,
                    "violation": "WEAK_EVIDENCE_IDENTITY_PROMOTION",
                    "state": canonical_state,
                    "reason_codes": list(reasons),
                }
            )
        if row["production_activated"]:
            violations.append(
                {
                    "source_id": source_id,
                    "violation": "SHADOW_MODE_PRODUCTION_ACTIVATION",
                }
            )

    return {
        "mode": "SHADOW_NON_ACTIVATING",
        "record_count": len(rows),
        "records": rows,
        "violations": violations,
        "pass": not violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--parameters", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    records = _load_json_or_jsonl(args.input)
    parameters_payload = json.loads(args.parameters.read_text(encoding="utf-8"))
    if not isinstance(parameters_payload, dict):
        raise ValueError("parameter file must be a JSON object")
    parameters = {str(key): float(value) for key, value in parameters_payload.items()}
    report = run_shadow_mode(records, parameters)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if args.check and not report["pass"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
