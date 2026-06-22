"""L3 SATIM calibration: FR24 vision/OCR field scoring."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from .models import LayerCalibrationResult, write_json

FIELD_THRESHOLDS = {
    "callsign": 0.90,
    "altitude_ft": 0.90,
    "aircraft_type": 0.90,
    "origin_code": 0.80,
    "destination_code": 0.80,
    "nearest_location": 0.70,
}


def normalize(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def normalize_int(value: Any) -> str:
    text = normalize(value).replace(",", "")
    try:
        return str(int(float(text)))
    except Exception:
        return text


def normalized_truth_value(field: str, row: Mapping[str, Any]) -> str:
    if field == "altitude_ft":
        return normalize_int(row.get(field))
    return normalize(row.get(field))


def speed_to_mph(value: Any, unit: Any) -> float | None:
    try:
        numeric = float(str(value).replace(",", "").strip())
    except Exception:
        return None
    unit_text = normalize(unit)
    if unit_text in {"KT", "KTS", "KNOT", "KNOTS"}:
        return round(numeric * 1.15078, 2)
    if unit_text in {"MPH", "MI/H"}:
        return round(numeric, 2)
    return None


def load_ground_truth(path: str | Path) -> List[Dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_predictions(path: str | Path) -> Dict[str, Dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {str(row.get("image_path", row.get("path", ""))): row for row in data}
    if isinstance(data, dict) and "records" in data:
        return {str(row.get("image_path", row.get("path", ""))): row for row in data["records"]}
    if isinstance(data, dict):
        return {str(k): v for k, v in data.items() if isinstance(v, dict)}
    return {}


def compare_field(field: str, truth: Mapping[str, Any], pred: Mapping[str, Any]) -> bool:
    if field == "altitude_ft":
        return normalize_int(truth.get(field)) == normalize_int(pred.get(field))
    return normalize(truth.get(field)) == normalize(pred.get(field))


def score_records(
    truth_rows: Iterable[Mapping[str, Any]],
    predictions: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    rows = list(truth_rows)

    totals = {field: 0 for field in FIELD_THRESHOLDS}
    matches = {field: 0 for field in FIELD_THRESHOLDS}
    blank_truth_skips = {field: 0 for field in FIELD_THRESHOLDS}
    missing_predictions = 0

    for row in rows:
        image_path = str(row.get("image_path", "")).strip()
        pred = predictions.get(image_path, {})

        row_has_scored_truth = False

        for field in FIELD_THRESHOLDS:
            if not normalized_truth_value(field, row):
                blank_truth_skips[field] += 1
                continue

            row_has_scored_truth = True
            totals[field] += 1

            if pred and compare_field(field, row, pred):
                matches[field] += 1

        if row_has_scored_truth and not pred:
            missing_predictions += 1

    field_scores = {
        field: (matches[field] / totals[field] if totals[field] else None)
        for field in FIELD_THRESHOLDS
    }

    return {
        "field_scores": field_scores,
        "field_observation_counts": totals,
        "blank_truth_skips": blank_truth_skips,
        "missing_predictions": missing_predictions,
        "record_count": len(rows),
        "scored_value_count": sum(totals.values()),
    }


def calibrate(ground_truth: str, predictions: str) -> Dict[str, Any]:
    rows = load_ground_truth(ground_truth)
    preds = load_predictions(predictions)
    metrics = score_records(rows, preds)

    findings = []

    if not rows:
        status = "MISSING"
        findings.append({
            "severity": "blocker",
            "detail": "no ground-truth rows available",
        })
    elif metrics["scored_value_count"] == 0:
        status = "MISSING"
        findings.append({
            "severity": "blocker",
            "detail": "no nonblank ground-truth values available for scoring",
        })
    else:
        for field, threshold in FIELD_THRESHOLDS.items():
            score = metrics["field_scores"].get(field)

            if score is None:
                findings.append({
                    "severity": "warning",
                    "field": field,
                    "detail": "no nonblank ground-truth values available for field",
                })
            elif score < threshold:
                findings.append({
                    "severity": "blocker",
                    "field": field,
                    "detail": "field score below calibration threshold",
                })

        if metrics["missing_predictions"]:
            findings.append({
                "severity": "warning",
                "detail": f"{metrics['missing_predictions']} ground-truth rows lack predictions",
            })

        status = "READY" if not findings else (
            "DEGRADED" if any(f["severity"] == "blocker" for f in findings) else "PARTIAL"
        )

    return LayerCalibrationResult(
        layer="L3_vision_ocr",
        status=status,
        metrics=metrics,
        thresholds=FIELD_THRESHOLDS,
        findings=findings,
    ).to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Score SATIM L3 OCR/vision predictions against ground truth")
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    write_json(args.output, calibrate(args.ground_truth, args.predictions))


if __name__ == "__main__":
    main()
