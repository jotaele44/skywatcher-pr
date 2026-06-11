#!/usr/bin/env python3
"""Verify additive ILAP_SCORE consistency in a CSV output file.

The check passes only when every row satisfies:

    ILAP_SCORE == sum(component score columns)

By default, component columns are every CSV column whose name starts with
`score_`, excluding `ILAP_SCORE` itself.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence


def to_number(value: object, field: str, row_index: int) -> float:
    if value is None or str(value).strip() == "":
        raise ValueError(f"row {row_index}: missing value for {field}")
    try:
        return float(value)
    except Exception as exc:
        raise ValueError(f"row {row_index}: non-numeric value for {field}: {value!r}") from exc


def infer_score_columns(fieldnames: Sequence[str]) -> List[str]:
    return [name for name in fieldnames if name.startswith("score_") and name != "ILAP_SCORE"]


def verify_csv(csv_path: Path, score_columns: Optional[List[str]], tolerance: float, output_json: Optional[Path]) -> int:
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")
    if csv_path.stat().st_size == 0:
        raise SystemExit(f"CSV is zero bytes: {csv_path}")

    failures: List[Dict[str, object]] = []
    row_count = 0
    detected_columns: List[str] = []

    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit("CSV has no header")
        if "ILAP_SCORE" not in reader.fieldnames:
            raise SystemExit("CSV is missing required ILAP_SCORE column")

        detected_columns = score_columns if score_columns else infer_score_columns(reader.fieldnames)
        if not detected_columns:
            raise SystemExit("No score component columns found. Expected columns starting with score_ or pass --score-columns.")

        missing = [col for col in detected_columns if col not in reader.fieldnames]
        if missing:
            raise SystemExit(f"CSV is missing declared score component columns: {missing}")

        for row_index, row in enumerate(reader, start=2):
            row_count += 1
            expected = sum(to_number(row.get(col), col, row_index) for col in detected_columns)
            observed = to_number(row.get("ILAP_SCORE"), "ILAP_SCORE", row_index)
            delta = observed - expected
            if abs(delta) > tolerance:
                failures.append({
                    "row_index": row_index,
                    "candidate_id": row.get("candidate_id", ""),
                    "observed_ILAP_SCORE": observed,
                    "expected_sum": expected,
                    "delta": delta,
                    "score_columns": {col: row.get(col) for col in detected_columns},
                })

    status = "PASS" if not failures else "FAIL"
    report = {
        "status": status,
        "csv_path": str(csv_path),
        "row_count": row_count,
        "score_columns": detected_columns,
        "tolerance": tolerance,
        "failure_count": len(failures),
        "failures": failures[:100],
    }

    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps({k: v for k, v in report.items() if k != "failures"}, indent=2))
    if failures:
        print("First failures:")
        for failure in failures[:10]:
            print(f"  row {failure['row_index']} candidate={failure['candidate_id']} observed={failure['observed_ILAP_SCORE']} expected={failure['expected_sum']} delta={failure['delta']}")
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Verify ILAP_SCORE equals the sum of component score columns.")
    p.add_argument("--csv", required=True, help="Candidate CSV containing ILAP_SCORE and component score columns.")
    p.add_argument("--score-columns", default="", help="Comma-separated score component columns. Default: infer columns starting with score_.")
    p.add_argument("--tolerance", type=float, default=0.000001, help="Numeric tolerance for equality check.")
    p.add_argument("--output-json", default="", help="Optional JSON report path.")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    score_columns = [x.strip() for x in args.score_columns.split(",") if x.strip()] or None
    output_json = Path(args.output_json).expanduser().resolve() if args.output_json else None
    return verify_csv(Path(args.csv).expanduser().resolve(), score_columns, args.tolerance, output_json)


if __name__ == "__main__":
    raise SystemExit(main())
