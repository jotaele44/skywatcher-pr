"""Manifest, receipts, and coverage ledgers for certified imagery acquisition."""
from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .core import CertifiedFetchResult, CoverageSummary


class ManifestEngine:
    def __init__(self, manifest_root: Path) -> None:
        self.manifest_root = Path(manifest_root)

    def write_csv(self, relative_path: str, rows: Iterable[Mapping[str, object]], fieldnames: Sequence[str]) -> Path:
        path = self.manifest_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        materialized = [dict(row) for row in rows]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
            writer.writeheader()
            writer.writerows(materialized)
        return path

    def write_source_manifest(self, rows: Iterable[Mapping[str, object]], filename: str = "source_manifest.csv") -> Path:
        materialized = [dict(row) for row in rows]
        fields = list(dict.fromkeys(k for row in materialized for k in row.keys())) or ["source_id"]
        return self.write_csv(filename, materialized, fields)

    def write_fetch_receipts(self, records: Sequence[CertifiedFetchResult], filename: str = "fetch_receipts.csv") -> Path:
        fields = list(CertifiedFetchResult.__dataclass_fields__.keys())
        return self.write_csv(filename, [asdict(record) for record in records], fields)

    def write_sha256_manifest(self, records: Sequence[CertifiedFetchResult], filename: str = "sha256_manifest.csv") -> Path:
        rows = [
            {
                "request_id": r.request_id,
                "source_lineage_id": r.source_lineage_id,
                "filename": r.filename,
                "sha256": r.sha256,
                "bytes": r.bytes,
                "review_status": r.review_status,
                "change_state": r.change_state,
            }
            for r in records
        ]
        return self.write_csv(filename, rows, ["request_id", "source_lineage_id", "filename", "sha256", "bytes", "review_status", "change_state"])

    def write_coverage_ledger(self, summary: CoverageSummary, filename: str = "coverage_ledger.csv") -> Path:
        row = {
            "expected": summary.expected,
            "requested": summary.requested,
            "acquired": summary.acquired,
            "failed": summary.failed,
            "hold": summary.hold,
            "cache_hit": summary.cache_hit,
            "unresolved": summary.unresolved,
            "coverage_pct": summary.coverage_pct,
        }
        return self.write_csv(filename, [row], list(row.keys()))


def summarize_coverage(expected: int, requested: int, records: Sequence[CertifiedFetchResult]) -> CoverageSummary:
    acquired = sum(1 for r in records if r.review_status in {"raw", "validated", "promoted", "cache_hit", "unchanged"})
    failed = sum(1 for r in records if r.review_status == "failed")
    hold = sum(1 for r in records if r.review_status == "hold")
    cache_hit = sum(1 for r in records if r.review_status == "cache_hit")
    return CoverageSummary(expected=expected, requested=requested, acquired=acquired, failed=failed, hold=hold, cache_hit=cache_hit, unresolved=failed + hold)
