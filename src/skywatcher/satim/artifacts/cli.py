from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .confidence_ledger import ConfidenceLedger
from .engine import ENGINE_VERSION, RULESET_VERSION, ArtifactAssessmentEngine
from .schema_validator import ArtifactSchemaValidator


def build_ledger_entry(payload: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    """Shape an assessment result into a satim_confidence_ledger_entry_v1 record.

    ``ConfidenceLedger.append`` supplies ``previous_entry_hash`` and
    ``entry_hash``; every other required field is populated here.
    """
    canonical_input = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {
        "ledger_id": str(uuid.uuid4()),
        "assessment_id": payload["assessment_id"],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "engine_version": ENGINE_VERSION,
        "ruleset_version": RULESET_VERSION,
        "input_sha256": hashlib.sha256(canonical_input).hexdigest(),
        "support": [],
        "contradictions": [{"detail": c} for c in result["contradictions"]],
        "caps": list(result["rules_triggered"]),
        "class_score": result["classification_confidence"],
        "origin_score": result["origin_confidence"],
        "decision": {
            "primary_class": result["primary_class"],
            "contributing_classes": result["contributing_classes"],
            "confidence_level": result["confidence_level"],
            "interpretation_restriction": result["interpretation_restriction"],
            "origin_layer": result["origin_layer"],
        },
    }


def build_parser():
    p = argparse.ArgumentParser(description="Assess SATIM imagery artifacts")
    p.add_argument("assessment")
    p.add_argument("--schema", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--ledger")
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    payload = json.loads(Path(a.assessment).read_text())
    ArtifactSchemaValidator(a.schema).require_valid(payload)
    result = ArtifactAssessmentEngine().assess(payload).to_dict()
    Path(a.output).write_text(json.dumps(result, indent=2, sort_keys=True))
    if a.ledger:
        ConfidenceLedger(a.ledger).append(build_ledger_entry(payload, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
