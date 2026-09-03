#!/usr/bin/env python3
"""Build the Skywatcher FR24 source-drop manifest from local evidence files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
FR24 = Path("/Users/jotaele/Documents/FR24")
FINANCIALS = Path("/Users/jotaele/Documents/Financials")

DROP_SOURCES = [
    {
        "source_id": "fr24_exports",
        "classification": "FOUND",
        "path": FR24 / "FR24_DataBank/Media_Canonical/freeze_final/final_active_media_index.csv",
        "inclusion_decision": "load_into_runtime_fr24_db",
        "blocker": "Real FR24 media inventory found; geometry still must be proven per observation.",
    },
    {
        "source_id": "fr24_aircraft_observations",
        "classification": "FOUND",
        "path": FINANCIALS / "Consolidated/entities/aircraft_observations.csv",
        "inclusion_decision": "load_into_runtime_fr24_db",
        "blocker": "Aircraft identity/kinematic OCR rows found; no lat/lon fields present.",
    },
    {
        "source_id": "fr24_manual_review",
        "classification": "FOUND",
        "path": FINANCIALS / "Consolidated/entities/manual_review_aircraft_identity.csv",
        "inclusion_decision": "manifest_and_review_accounting",
        "blocker": "Manual review ledger found; unresolved identities remain review-bound.",
    },
    {
        "source_id": "fr24_certification_summary",
        "classification": "FOUND",
        "path": FR24 / "FR24_DataBank/Media_Canonical/freeze_final/final_certification_summary.json",
        "inclusion_decision": "manifest_certification_receipt",
        "blocker": "FR24 media certification receipt found.",
    },
    {
        "source_id": "fr24_ocr_identity_certification",
        "classification": "FOUND",
        "path": FR24 / "FR24_DataBank/Media_Canonical/freeze_final/ocr_identity_certification.json",
        "inclusion_decision": "manifest_certification_receipt",
        "blocker": "OCR identity certification receipt found.",
    },
    {
        "source_id": "fr24_reviewer_bundle",
        "classification": "FOUND",
        "path": FR24 / "FR24_DataBank/Media_Canonical/reviewer_bundle/FR24_reviewer_bundle.zip",
        "inclusion_decision": "manifest_review_bundle",
        "blocker": "Reviewer bundle found; not a promoted observation source by itself.",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_csv(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        rows = sum(1 for _ in reader)
    return {"format": "csv", "logical_rows": rows, "header": header}


def inspect_path(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    info: dict[str, Any] = {
        "exists": True,
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    suffix = path.suffix.lower()
    if suffix == ".csv":
        info.update(inspect_csv(path))
    elif suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        info.update({"format": "json", "top_level_keys": sorted(data) if isinstance(data, dict) else []})
    elif suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            info.update({
                "format": "zip",
                "member_count": len(archive.infolist()),
                "members": [
                    {"path": m.filename, "uncompressed_size": m.file_size}
                    for m in archive.infolist()[:100]
                ],
            })
    else:
        info["format"] = suffix.lstrip(".") or "unknown"
    return info


def build_records() -> list[dict[str, Any]]:
    records = []
    for item in DROP_SOURCES:
        path = Path(item["path"])
        records.append({
            "source_id": item["source_id"],
            "classification": item["classification"],
            "inclusion_decision": item["inclusion_decision"],
            "blocker_classification_note": item["blocker"],
            "absolute_source_path": str(path),
            "raw_normalized_canonical_policy": "Preserve raw source strings; no mission or intent inference from labels, proximity, geometry, or gaps.",
            **inspect_path(path),
        })
    return records


def write_outputs(records: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "producer": "skywatcher-pr",
        "generated_at": utc_now(),
        "lumen_status": "unavailable_in_session",
        "records": records,
        "arithmetic": {
            "total": len(records),
            "found": sum(1 for r in records if r["classification"] == "FOUND"),
            "missing_files": sum(1 for r in records if not r.get("exists")),
        },
    }
    (out_dir / "skywatcher_source_drop_manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    fields = [
        "source_id", "classification", "inclusion_decision", "absolute_source_path",
        "exists", "byte_size", "sha256", "logical_rows", "blocker_classification_note",
    ]
    with (out_dir / "skywatcher_source_drop_manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    print(json.dumps(payload["arithmetic"], sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "reports" / "source_drops"))
    args = parser.parse_args()
    write_outputs(build_records(), Path(args.out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
