"""
FR24 OCR PROBE

Read-only OCR probe for a small validated subset of FR24 screenshots. This is
intended to validate OCR yield before full-corpus OCR. It prefers strong
sidecar-linked images from fr24_manifest_with_sidecars.csv and writes JSONL/CSV
outputs under the selected output directory.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import List

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


def _append_bucket(selected: List[dict], seen: set, bucket: List[dict], remaining: int) -> int:
    if remaining <= 0:
        return 0
    added = 0
    for row in bucket:
        if added >= remaining:
            break
        image_path = row.get("image_path")
        if image_path in seen:
            continue
        selected.append(row)
        seen.add(image_path)
        added += 1
    return added


def _write_probe_csv(output_csv: Path, rows: List[dict], selected: List[dict]) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else [
        "image_path",
        "image_name",
        "sidecar_path",
        "sidecar_title",
        "match_band",
        "resolved_status",
        "review_status",
    ]
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in selected:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def select_probe(manifest_csv: Path, output_csv: Path, limit: int = 50, png_count: int = 30, heic_count: int = 15) -> List[dict]:
    rows = list(csv.DictReader(manifest_csv.open(encoding="utf-8")))
    if limit <= 0:
        _write_probe_csv(output_csv, rows, [])
        return []

    strong = [
        r
        for r in rows
        if r.get("resolved_status") == "matched_primary"
        and r.get("match_band") == "strong"
        and r.get("review_status") == "sidecar_linked"
    ]
    heic = [r for r in strong if r.get("image_name", "").lower().endswith(".heic")]
    png = [r for r in strong if r.get("image_name", "").lower().endswith(".png")]
    other = [r for r in strong if not r.get("image_name", "").lower().endswith((".heic", ".png"))]

    selected: List[dict] = []
    seen = set()

    remaining = limit - len(selected)
    _append_bucket(selected, seen, heic, min(heic_count, remaining))
    remaining = limit - len(selected)
    _append_bucket(selected, seen, png, min(png_count, remaining))
    remaining = limit - len(selected)
    _append_bucket(selected, seen, other, remaining)

    # Fill any remaining slots from the full strong pool while preserving the limit.
    remaining = limit - len(selected)
    _append_bucket(selected, seen, strong, remaining)

    _write_probe_csv(output_csv, rows, selected)
    return selected


def _ocr_image(path: Path) -> str:
    if Image is None or ImageOps is None:
        raise RuntimeError("Pillow is required for OCR probe")
    if pytesseract is None:
        raise RuntimeError("pytesseract is required for OCR probe")
    with Image.open(path) as img:
        img.load()
        img = ImageOps.exif_transpose(img)
        img = img.convert("L")
        return pytesseract.image_to_string(img)


def _write_empty_probe_outputs(input_csv: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = output_dir / "fr24_ocr_probe_50.jsonl"
    out_csv = output_dir / "fr24_ocr_probe_50_results.csv"
    summary_path = output_dir / "fr24_ocr_probe_50_summary.json"
    out_jsonl.write_text("", encoding="utf-8")
    csv_fields = [
        "index",
        "image_path",
        "image_name",
        "sidecar_title",
        "match_band",
        "resolved_status",
        "review_status",
        "ocr_status",
        "ocr_char_count",
        "error",
    ]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_csv": str(input_csv),
        "total": 0,
        "complete": 0,
        "failed": 0,
        "zero_or_low_text_under_20_chars": 0,
        "extension_mix": {},
        "jsonl": str(out_jsonl),
        "csv": str(out_csv),
        "status": "no_eligible_probe_rows",
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def run_ocr_probe(input_csv: Path, output_dir: Path) -> dict:
    if not input_csv.exists():
        return _write_empty_probe_outputs(input_csv, output_dir)
    rows = list(csv.DictReader(input_csv.open(encoding="utf-8")))
    if not rows:
        return _write_empty_probe_outputs(input_csv, output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = output_dir / "fr24_ocr_probe_50.jsonl"
    out_csv = output_dir / "fr24_ocr_probe_50_results.csv"
    summary_path = output_dir / "fr24_ocr_probe_50_summary.json"

    results = []
    for index, row in enumerate(rows, 1):
        image_path = Path(row["image_path"])
        rec = {
            "index": index,
            "image_path": str(image_path),
            "image_name": row.get("image_name", ""),
            "sidecar_path": row.get("sidecar_path", ""),
            "sidecar_title": row.get("sidecar_title", ""),
            "match_band": row.get("match_band", ""),
            "resolved_status": row.get("resolved_status", ""),
            "review_status": row.get("review_status", ""),
            "ocr_status": "not_run",
            "ocr_text": "",
            "ocr_char_count": 0,
            "error": "",
        }
        try:
            text = _ocr_image(image_path)
            rec["ocr_status"] = "complete"
            rec["ocr_text"] = text
            rec["ocr_char_count"] = len(text.strip())
        except Exception as exc:
            rec["ocr_status"] = "failed"
            rec["error"] = repr(exc)
        results.append(rec)

    with out_jsonl.open("w", encoding="utf-8") as f:
        for rec in results:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    csv_fields = [
        "index",
        "image_path",
        "image_name",
        "sidecar_title",
        "match_band",
        "resolved_status",
        "review_status",
        "ocr_status",
        "ocr_char_count",
        "error",
    ]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        for rec in results:
            writer.writerow({k: rec.get(k, "") for k in csv_fields})

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_csv": str(input_csv),
        "total": len(results),
        "complete": sum(r["ocr_status"] == "complete" for r in results),
        "failed": sum(r["ocr_status"] == "failed" for r in results),
        "zero_or_low_text_under_20_chars": sum(int(r["ocr_char_count"] or 0) < 20 for r in results),
        "extension_mix": dict(Counter(Path(r["image_name"]).suffix.lower() for r in results)),
        "jsonl": str(out_jsonl),
        "csv": str(out_csv),
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Select and OCR a small FR24 screenshot probe")
    parser.add_argument("--manifest", default="data/_manifests/fr24_audit/fr24_manifest_with_sidecars.csv")
    parser.add_argument("--output-dir", default="data/_manifests/fr24_audit")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--select-only", action="store_true", help="Only write the probe CSV; do not run OCR")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    probe_csv = output_dir / "fr24_ocr_probe_50.csv"
    selected = select_probe(Path(args.manifest), probe_csv, args.limit)
    print(json.dumps({"selected": len(selected), "output_csv": str(probe_csv)}, indent=2))
    if not args.select_only:
        print(json.dumps(run_ocr_probe(probe_csv, output_dir), indent=2))


if __name__ == "__main__":
    main()
