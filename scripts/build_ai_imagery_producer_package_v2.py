#!/usr/bin/env python3
"""Build an offline deterministic ADR 0006 Skywatcher producer package v2."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from skywatcher.ai_imagery.producer_package import (
    ProducerPackageError,
    build_package,
    write_package,
)


def _read(path: str | None) -> list[dict]:
    if path is None:
        return []
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        value = json.loads(text)
        if not isinstance(value, list):
            raise ValueError(f"{path} must contain a JSON array or JSONL")
        return value
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic offline package v2")
    parser.add_argument("--producer-revision", required=True)
    parser.add_argument("--source-artifacts", required=True)
    parser.add_argument("--aviation-extractions", required=True)
    parser.add_argument("--field-provenance", required=True)
    parser.add_argument("--provisional-signals", required=True)
    parser.add_argument("--processing-receipts", required=True)
    parser.add_argument("--exclusions")
    parser.add_argument("--failures")
    parser.add_argument("--created-at")
    parser.add_argument("--package-id")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    created_at = args.created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        envelope, collections = build_package(
            producer_revision=args.producer_revision,
            created_at=created_at,
            package_id=args.package_id,
            source_artifacts=_read(args.source_artifacts),
            aviation_extractions=_read(args.aviation_extractions),
            model_field_provenance=_read(args.field_provenance),
            provisional_signals=_read(args.provisional_signals),
            processing_receipts=_read(args.processing_receipts),
            exclusions=_read(args.exclusions),
            failures=_read(args.failures),
        )
        write_package(Path(args.out), envelope, collections)
    except (OSError, ValueError, json.JSONDecodeError, ProducerPackageError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(envelope, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
