"""
FR24 BATCH RUNNER

Resumable full-corpus OCR batch runner.  Reads a batch plan CSV, processes a
single requested batch_id, and writes OCR results to per-batch JSONL files.
Completed images are tracked in a ledger CSV; re-running the same batch_id
skips already-complete images.

Modes
-----
  --mode whole-image   Run Tesseract on the full image.
  --mode region        Segment image with FR24UISegmenter, then OCR each region.

Resumability
------------
  Before processing each image, the ledger is checked for a row with
  (image_path, batch_id, mode, status=complete).  If found, the image is
  skipped.  Failed images are written to the error queue but do not halt the
  batch.

Outputs
-------
  batches/fr24_batch_<id>_ocr.jsonl          whole-image OCR records
  batches/fr24_batch_<id>_region_ocr.jsonl   region OCR records
  batches/fr24_batch_<id>_status.json        batch completion summary
  fr24_batch_run_ledger.csv                  append-mode run ledger
  fr24_batch_error_queue.csv                 error queue (append)

Source images are never mutated.  Raw files are never deleted or moved.
No confirmed labels are emitted.
"""

from __future__ import annotations

import argparse
import csv
import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None  # type: ignore
    ImageOps = None  # type: ignore

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass

try:
    import pytesseract
except ImportError:
    pytesseract = None  # type: ignore

from fr24.ui_segmenter import FR24UISegmenter

PARSER_VERSION = "1.0.0"

LEDGER_FIELDS = [
    "ledger_id",
    "batch_id",
    "mode",
    "batch_seq",
    "image_path",
    "image_name",
    "started_at",
    "completed_at",
    "status",
    "ocr_char_count",
    "regions_ocr_count",
    "error",
]

ERROR_QUEUE_FIELDS = [
    "ledger_id",
    "batch_id",
    "mode",
    "batch_seq",
    "image_path",
    "image_name",
    "started_at",
    "error",
]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_complete_set(ledger_path: Path, batch_id: str, mode: str) -> Set[str]:
    if not ledger_path.exists():
        return set()
    complete = set()
    with ledger_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (
                row.get("batch_id") == batch_id
                and row.get("mode") == mode
                and row.get("status") == "complete"
            ):
                complete.add(row.get("image_path", ""))
    return complete


def _append_ledger(ledger_path: Path, row: dict) -> None:
    is_new = not ledger_path.exists()
    with ledger_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LEDGER_FIELDS, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in LEDGER_FIELDS})


def _append_error_queue(error_path: Path, row: dict) -> None:
    is_new = not error_path.exists()
    with error_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ERROR_QUEUE_FIELDS, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in ERROR_QUEUE_FIELDS})


def _ocr_full_image(path: Path) -> Tuple[str, int]:
    if Image is None:
        raise RuntimeError("Pillow is required for OCR")
    if pytesseract is None:
        raise RuntimeError("pytesseract is required for OCR")
    with Image.open(path) as img:
        img.load()
        img = ImageOps.exif_transpose(img)
        img = img.convert("L")
        text = pytesseract.image_to_string(img)
    return text, len(text.strip())


def _ocr_regions(path: Path, segmenter: FR24UISegmenter) -> List[dict]:
    if Image is None:
        raise RuntimeError("Pillow is required for region OCR")
    if pytesseract is None:
        raise RuntimeError("pytesseract is required for region OCR")

    segs = segmenter.segment(str(path))
    results = []

    region_defs = [
        ("panel", "panel", segs.panel_bbox),
    ]
    for label in segs.labels:
        region_defs.append((label.region_type, label.region_type, label.bbox))

    with Image.open(path) as img:
        img.load()
        img = ImageOps.exif_transpose(img)

        for ocr_region, region_type, bbox in region_defs:
            crop_coords = bbox.crop_coords()
            try:
                cropped = img.crop(crop_coords).convert("L")
                text = pytesseract.image_to_string(cropped)
                char_count = len(text.strip())
                results.append({
                    "ocr_region": ocr_region,
                    "region_type": region_type,
                    "region_bbox": {"x": bbox.x, "y": bbox.y, "w": bbox.w, "h": bbox.h},
                    "ocr_text": text,
                    "ocr_char_count": char_count,
                    "ocr_status": "complete",
                    "parser_version": PARSER_VERSION,
                    "error": "",
                })
            except Exception as exc:
                results.append({
                    "ocr_region": ocr_region,
                    "region_type": region_type,
                    "region_bbox": {"x": bbox.x, "y": bbox.y, "w": bbox.w, "h": bbox.h},
                    "ocr_text": "",
                    "ocr_char_count": 0,
                    "ocr_status": "failed",
                    "parser_version": PARSER_VERSION,
                    "error": repr(exc),
                })
    return results


def run_batch(
    batch_plan: Path,
    batch_id: str,
    mode: str,
    output_dir: Path,
    limit: Optional[int] = None,
) -> dict:
    batch_rows: List[dict] = []
    with batch_plan.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("batch_id") == batch_id:
                batch_rows.append(row)

    if limit and limit > 0:
        batch_rows = batch_rows[:limit]

    output_dir.mkdir(parents=True, exist_ok=True)
    batches_dir = output_dir / "batches"
    batches_dir.mkdir(parents=True, exist_ok=True)

    ledger_path = output_dir / "fr24_batch_run_ledger.csv"
    error_path = output_dir / "fr24_batch_error_queue.csv"

    if mode == "whole-image":
        out_jsonl = batches_dir / f"{batch_id}_ocr.jsonl"
    else:
        out_jsonl = batches_dir / f"{batch_id}_region_ocr.jsonl"

    complete_set = _load_complete_set(ledger_path, batch_id, mode)
    segmenter = FR24UISegmenter(mode="geometric") if mode == "region" else None

    stats: Dict[str, int] = Counter()
    written_records: List[dict] = []

    for plan_row in batch_rows:
        image_path_str = plan_row.get("image_path", "")
        image_name = plan_row.get("image_name", "")
        batch_seq = plan_row.get("batch_seq", "")

        if image_path_str in complete_set:
            stats["skipped"] += 1
            continue

        started = _utcnow()
        ledger_row = {
            "ledger_id": str(uuid.uuid4()),
            "batch_id": batch_id,
            "mode": mode,
            "batch_seq": batch_seq,
            "image_path": image_path_str,
            "image_name": image_name,
            "started_at": started,
            "completed_at": "",
            "status": "failed",
            "ocr_char_count": 0,
            "regions_ocr_count": 0,
            "error": "",
        }

        image_path = Path(image_path_str)
        base_record = {
            "image_path": image_path_str,
            "image_name": image_name,
            "sidecar_path": plan_row.get("sidecar_path", ""),
            "sidecar_title": plan_row.get("sidecar_title", ""),
            "match_band": plan_row.get("match_band", ""),
            "resolved_status": plan_row.get("resolved_status", ""),
            "batch_id": batch_id,
            "batch_seq": batch_seq,
        }

        try:
            if mode == "whole-image":
                text, char_count = _ocr_full_image(image_path)
                record = {
                    **base_record,
                    "ocr_status": "complete",
                    "ocr_text": text,
                    "ocr_char_count": char_count,
                    "error": "",
                }
                written_records.append(record)
                ledger_row["ocr_char_count"] = char_count
                ledger_row["regions_ocr_count"] = 1
                ledger_row["status"] = "complete"
                stats["complete"] += 1

            else:
                region_results = _ocr_regions(image_path, segmenter)  # type: ignore[arg-type]
                for res in region_results:
                    record = {**base_record, **res}
                    written_records.append(record)
                total_chars = sum(r.get("ocr_char_count", 0) for r in region_results)
                ledger_row["ocr_char_count"] = total_chars
                ledger_row["regions_ocr_count"] = len(region_results)
                ledger_row["status"] = "complete"
                stats["complete"] += 1

        except Exception as exc:
            ledger_row["error"] = repr(exc)
            stats["failed"] += 1
            _append_error_queue(error_path, {
                **ledger_row,
                "started_at": started,
            })

        ledger_row["completed_at"] = _utcnow()
        _append_ledger(ledger_path, ledger_row)

    with out_jsonl.open("w", encoding="utf-8") as f:
        for rec in written_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    status_json = {
        "generated_at": _utcnow(),
        "batch_id": batch_id,
        "mode": mode,
        "total": len(batch_rows),
        "complete": stats.get("complete", 0),
        "failed": stats.get("failed", 0),
        "skipped": stats.get("skipped", 0),
        "output_jsonl": str(out_jsonl),
        "ledger": str(ledger_path),
        "error_queue": str(error_path),
    }
    status_path = batches_dir / f"{batch_id}_status.json"
    status_path.write_text(json.dumps(status_json, indent=2), encoding="utf-8")
    return status_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a resumable FR24 OCR batch")
    parser.add_argument("--batch-plan", default="data/_manifests/fr24_audit/fr24_full_corpus_batch_plan.csv")
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--mode", choices=["whole-image", "region"], default="whole-image")
    parser.add_argument("--output-dir", default="data/_manifests/fr24_audit")
    parser.add_argument("--limit", type=int, default=0, help="Max images to process (0 = all)")
    args = parser.parse_args()

    summary = run_batch(
        batch_plan=Path(args.batch_plan),
        batch_id=args.batch_id,
        mode=args.mode,
        output_dir=Path(args.output_dir),
        limit=args.limit if args.limit > 0 else None,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
