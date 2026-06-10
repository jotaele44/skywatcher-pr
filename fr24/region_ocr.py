"""
FR24 REGION OCR PROBE

Read-only region-based text extraction for FR24 screenshots. This module crops
predefined screen regions from selected manifest rows and sends each crop to
Tesseract. Outputs are candidate-only and require review.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = None  # type: ignore
    ImageOps = None  # type: ignore

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover
    pass

try:
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None  # type: ignore

REGION_FRACTIONS: Dict[str, Tuple[float, float, float, float]] = {
    "full_image": (0.0, 0.0, 1.0, 1.0),
    "right_panel": (0.66, 0.0, 1.0, 1.0),
    "top_bar": (0.0, 0.0, 1.0, 0.14),
    "bottom_timeline": (0.0, 0.82, 1.0, 1.0),
    "map_area": (0.0, 0.10, 0.72, 0.88),
}


def load_manifest(path: Path) -> List[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def is_ocr_eligible(row: dict) -> bool:
    return row.get("ocr_status", "eligible") == "eligible"


def select_manifest_rows(rows: List[dict], limit: int, include_reviewable: bool = False) -> List[dict]:
    if limit <= 0:
        return []
    preferred = [
        r for r in rows
        if is_ocr_eligible(r)
        and r.get("resolved_status") == "matched_primary"
        and r.get("match_band") == "strong"
        and r.get("review_status") == "sidecar_linked"
    ]
    if include_reviewable:
        extras = [
            r for r in rows
            if r not in preferred
            and is_ocr_eligible(r)
            and (
                r.get("match_band") == "reviewable"
                or r.get("review_status") in {"weak_sidecar_match_review", "metadata_gap", "sidecar_conflict_review"}
            )
        ]
        preferred.extend(extras)
    return preferred[:limit]


def crop_box(width: int, height: int, frac: Tuple[float, float, float, float]) -> Tuple[int, int, int, int]:
    x0, y0, x1, y1 = frac
    return (
        max(0, min(width, int(width * x0))),
        max(0, min(height, int(height * y0))),
        max(0, min(width, int(width * x1))),
        max(0, min(height, int(height * y1))),
    )


def extract_text_region(image_path: Path, region_name: str) -> dict:
    if Image is None or ImageOps is None:
        raise RuntimeError("Pillow is required")
    if pytesseract is None:
        raise RuntimeError("pytesseract is required")
    if region_name not in REGION_FRACTIONS:
        raise ValueError(f"Unknown region: {region_name}")

    with Image.open(image_path) as img:
        img.load()
        img = ImageOps.exif_transpose(img)
        width, height = img.size
        box = crop_box(width, height, REGION_FRACTIONS[region_name])
        crop = img.crop(box).convert("L")
        text = pytesseract.image_to_string(crop)
        return {
            "region_name": region_name,
            "region_box": json.dumps(box),
            "text": text,
            "char_count": len(text.strip()),
        }


def run_region_ocr(manifest_csv: Path, output_dir: Path, limit: int = 50, include_reviewable: bool = False) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = load_manifest(manifest_csv)
    selected = select_manifest_rows(rows, limit, include_reviewable)

    jsonl_path = output_dir / "fr24_region_ocr_results.jsonl"
    csv_path = output_dir / "fr24_region_ocr_summary.csv"
    summary_path = output_dir / "fr24_region_ocr_summary.json"

    records: List[dict] = []
    for index, row in enumerate(selected, 1):
        image_path = Path(row.get("image_path", ""))
        for region_name in REGION_FRACTIONS:
            rec = {
                "index": index,
                "image_path": str(image_path),
                "image_name": row.get("image_name", ""),
                "sidecar_title": row.get("sidecar_title", ""),
                "match_band": row.get("match_band", ""),
                "source_review_status": row.get("review_status", ""),
                "region_name": region_name,
                "region_box": "",
                "extract_status": "not_run",
                "text": "",
                "char_count": 0,
                "error": "",
            }
            try:
                region = extract_text_region(image_path, region_name)
                rec["region_box"] = region["region_box"]
                rec["text"] = region["text"]
                rec["char_count"] = region["char_count"]
                rec["extract_status"] = "complete"
            except Exception as exc:
                rec["extract_status"] = "failed"
                rec["error"] = repr(exc)
            records.append(rec)

    with jsonl_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    csv_fields = [
        "index", "image_path", "image_name", "sidecar_title", "match_band",
        "source_review_status", "region_name", "region_box", "extract_status",
        "char_count", "error",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        for rec in records:
            writer.writerow({k: rec.get(k, "") for k in csv_fields})

    complete = [r for r in records if r["extract_status"] == "complete"]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_csv": str(manifest_csv),
        "selected_images": len(selected),
        "region_count": len(REGION_FRACTIONS),
        "total_region_records": len(records),
        "complete": len(complete),
        "failed": sum(r["extract_status"] == "failed" for r in records),
        "complete_by_region": dict(Counter(r["region_name"] for r in complete)),
        "low_text_under_20_by_region": dict(Counter(r["region_name"] for r in complete if int(r["char_count"] or 0) < 20)),
        "jsonl": str(jsonl_path),
        "csv": str(csv_path),
        "policy": "candidate_only_no_auto_confirmation",
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run region-based text extraction for FR24 screenshots")
    parser.add_argument("--manifest", default="data/_manifests/fr24_audit/fr24_manifest_with_sidecars.csv")
    parser.add_argument("--output-dir", default="data/_manifests/fr24_audit")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--include-reviewable", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_region_ocr(Path(args.manifest), Path(args.output_dir), args.limit, args.include_reviewable), indent=2))


if __name__ == "__main__":
    main()
