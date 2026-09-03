#!/usr/bin/env python3
"""Manifest-driven intake for analyst-provided Skywatcher/SATIM media.

The engine accepts local runtime files supplied by the operator. Source media are
not committed to the repository and are not hard-coded into ledgers.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".heic",
    ".heif",
    ".webp",
    ".tif",
    ".tiff",
}


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    return data


def validate_input_path(input_path: str) -> Path:
    path = Path(input_path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"unsupported input extension {ext!r}; allowed: {allowed}")
    return path


def build_event_stub(manifest: dict[str, Any]) -> dict[str, Any]:
    input_path = validate_input_path(str(manifest["input_path"]))
    run_id = str(manifest.get("run_id") or input_path.stem)

    return {
        "event_id": run_id,
        "source_packet": "runtime_input_not_committed",
        "source_app": manifest.get("source_app") or manifest.get("source_family") or "unknown",
        "observed_timestamp_local": manifest.get("observed_timestamp_local"),
        "observed_timestamp_utc": manifest.get("observed_timestamp_utc"),
        "aircraft_label": manifest.get("aircraft_label"),
        "registration": manifest.get("registration"),
        "callsign": manifest.get("callsign"),
        "route_summary": manifest.get("route_summary"),
        "geographic_context": manifest.get("geographic_context") or "runtime input; AOI not specified",
        "page_refs": manifest.get("page_refs") or [],
        "evidence_tier": manifest.get("evidence_tier") or "T4",
        "confidence": manifest.get("confidence") or "low",
        "qa_flags": sorted(set([
            "runtime_media_input",
            "source_media_not_committed",
            "artifact_controls_required",
            *manifest.get("qa_flags", []),
        ])),
        "notes": manifest.get("analyst_notes") or "Generated from runtime manifest; source media not committed.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="JSON manifest describing the runtime media input")
    parser.add_argument("--out", default="flight_event_ledger.jsonl")
    args = parser.parse_args()

    manifest = load_manifest(Path(args.manifest))
    if "input_path" not in manifest:
        raise ValueError("manifest requires input_path")

    row = build_event_stub(manifest)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
