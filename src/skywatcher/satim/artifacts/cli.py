from __future__ import annotations

import argparse
import json
from pathlib import Path

from .confidence_ledger import ConfidenceLedger
from .engine import ArtifactAssessmentEngine
from .schema_validator import ArtifactSchemaValidator


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
        ConfidenceLedger(a.ledger).append({"assessment_id": payload["assessment_id"], **result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
