#!/usr/bin/env python3
"""
FR24 Vision Ingest — extracts telemetry from FlightRadar24 HEIC screenshots
using Claude vision and outputs a CSV compatible with ingest_data.py.

Usage (from repo root):
    python3 scripts/fr24_vision_ingest.py                    # full run
    python3 scripts/fr24_vision_ingest.py --limit 20         # test run (~$0.03)
    python3 scripts/fr24_vision_ingest.py --limit 20 --output /tmp/test.csv

Requires:  pip3 install anthropic tqdm
           ANTHROPIC_API_KEY environment variable
           sips (macOS built-in, converts HEIC → JPEG)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

# Matches filenames like "2026-03-24 09-40-01.HEIC"
_FILENAME_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(\d{2})-(\d{2})-(\d{2})")

import anthropic

try:
    from tqdm.asyncio import tqdm as async_tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

ROOT = Path(__file__).parent.parent

DEFAULT_IMAGE_DIR = ROOT / "data" / "FR24 Logs"
DEFAULT_OUTPUT    = ROOT / "outputs" / "fr24_selected_export.csv"
DEFAULT_DB        = ROOT / "server" / "priis.db"
DEFAULT_CHECKPOINT = ROOT / "outputs" / "fr24_ingest_checkpoint.json"

EXTRACTION_PROMPT = """You are reading a FlightRadar24 mobile app screenshot showing a tracked aircraft over Puerto Rico.
Extract the following fields and return ONLY valid JSON — no prose, no markdown:

{
  "callsign": "",
  "aircraft_type": "",
  "operator": "",
  "registration": "",
  "origin_code": "",
  "destination_code": "",
  "altitude_ft": null,
  "ground_speed_mph": null,
  "flight_status": "",
  "playback_date": "",
  "playback_time": "",
  "nearest_location": ""
}

Field guidance:
- callsign: tail number (e.g. N5854Z) or flight code visible at top
- aircraft_type: model shown (e.g. Airbus H125, Bell 407, Phenom 300E)
- operator: airline or company name if visible
- registration: N-number or similar registration code
- origin_code / destination_code: IATA/ICAO airport codes (e.g. SJU, BQN)
- altitude_ft: barometric altitude as integer (null if not shown)
- ground_speed_mph: speed as integer (null if not shown)
- flight_status: e.g. "En Route", "Landed", "Scheduled", "On Ground"
- playback_date: date visible in app (YYYY-MM-DD format, or "" if not shown)
- playback_time: time visible in app (HH:MM 24h format, or "" if not shown)
- nearest_location: visible Puerto Rico place name, municipality, or landmark (or "")

If a field is not visible, use null for numbers and "" for strings."""


# ── Site mapping ────────────────────────────────────────────────────────────────

def load_sites(db_path: Path) -> list[tuple[str, str]]:
    """Return [(site_id, name_lower)] from priis.db if it exists."""
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT id, name FROM sites").fetchall()
        conn.close()
        return [(r[0], r[1].lower()) for r in rows]
    except Exception:
        return []


def match_site(nearest_location: str, sites: list[tuple[str, str]]) -> str | None:
    if not nearest_location or not sites:
        return None
    loc = nearest_location.lower()
    tokens = [t for t in loc.split() if len(t) > 3]
    for site_id, name_lower in sites:
        if loc in name_lower or name_lower in loc:
            return site_id
        if any(tok in name_lower for tok in tokens):
            return site_id
    return None


# ── HEIC → JPEG conversion ──────────────────────────────────────────────────────

def heic_to_jpeg_bytes(heic_path: Path) -> bytes | None:
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        r = subprocess.run(
            ["sips", "-s", "format", "jpeg", str(heic_path), "--out", tmp_path],
            capture_output=True, timeout=30,
        )
        if r.returncode != 0:
            return None
        return Path(tmp_path).read_bytes()
    except Exception:
        return None
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


# ── Claude extraction ───────────────────────────────────────────────────────────

async def extract_fields(
    client: anthropic.AsyncAnthropic,
    semaphore: asyncio.Semaphore,
    heic_path: Path,
    model: str,
) -> dict[str, Any]:
    async with semaphore:
        jpg_bytes = await asyncio.get_event_loop().run_in_executor(
            None, heic_to_jpeg_bytes, heic_path
        )
        if jpg_bytes is None:
            return {}

        img_b64 = base64.standard_b64encode(jpg_bytes).decode()
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=512,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": img_b64,
                            },
                        },
                        {"type": "text", "text": EXTRACTION_PROMPT},
                    ],
                }],
            )
            text = response.content[0].text if response.content else ""
            # Strip any accidental markdown fences
            text = text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        except Exception:
            return {}


# ── Row building ─────────────────────────────────────────────────────────────────

CSV_FIELDNAMES = [
    "id", "at", "label", "ref_id", "site_id",
    "callsign", "aircraft_type", "operator", "registration",
    "origin_code", "destination_code", "altitude_ft", "ground_speed_mph",
    "flight_status", "image_path", "month_dir",
]


def build_row(
    heic_path: Path,
    fields: dict[str, Any],
    sites: list[tuple[str, str]],
) -> dict[str, Any]:
    stem = heic_path.stem
    event_id = f"fr24-{stem}"

    # Timestamp priority:
    # 1. Filename pattern "YYYY-MM-DD HH-MM-SS.HEIC" (most reliable)
    # 2. App-displayed date+time from vision extraction
    # 3. File mtime fallback
    m = _FILENAME_TS_RE.match(heic_path.stem)
    if m:
        at = f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}"
    else:
        date_str = (fields.get("playback_date") or "").strip()
        time_str = (fields.get("playback_time") or "").strip()
        if date_str and time_str:
            at = f"{date_str}T{time_str}:00"
        elif date_str:
            at = f"{date_str}T00:00:00"
        else:
            mtime = heic_path.stat().st_mtime
            at = datetime.utcfromtimestamp(mtime).strftime("%Y-%m-%dT%H:%M:%S")

    callsign = (fields.get("callsign") or "").strip()
    site_id = match_site(fields.get("nearest_location") or "", sites)
    month_dir = heic_path.parent.name

    return {
        "id":               event_id,
        "at":               at,
        "label":            callsign or stem,
        "ref_id":           callsign,
        "site_id":          site_id or "",
        "callsign":         callsign,
        "aircraft_type":    (fields.get("aircraft_type") or "").strip(),
        "operator":         (fields.get("operator") or "").strip(),
        "registration":     (fields.get("registration") or "").strip(),
        "origin_code":      (fields.get("origin_code") or "").strip(),
        "destination_code": (fields.get("destination_code") or "").strip(),
        "altitude_ft":      fields.get("altitude_ft") or "",
        "ground_speed_mph": fields.get("ground_speed_mph") or "",
        "flight_status":    (fields.get("flight_status") or "").strip(),
        "image_path":       str(heic_path),
        "month_dir":        month_dir,
    }


# ── Checkpoint ───────────────────────────────────────────────────────────────────

def load_checkpoint(path: Path) -> set[str]:
    if path.exists():
        return set(json.loads(path.read_text()))
    return set()


def save_checkpoint(path: Path, processed: set[str]) -> None:
    path.write_text(json.dumps(sorted(processed), indent=2))


def _image_paths_in_csv(output_path: Path) -> set[str]:
    """Return the set of image_path values already written to the output CSV.

    Used by --retry-errors to tell successful extractions (in the CSV) apart
    from previously-checkpointed failures (not in the CSV).
    """
    if not output_path.exists() or output_path.stat().st_size == 0:
        return set()
    with output_path.open(newline="") as f:
        return {
            (row.get("image_path") or "").strip()
            for row in csv.DictReader(f)
            if (row.get("image_path") or "").strip()
        }


# ── Main ──────────────────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Error: ANTHROPIC_API_KEY environment variable is not set.")

    image_dir = Path(args.image_dir)
    output_path = Path(args.output)
    checkpoint_path = Path(args.checkpoint)
    db_path = Path(args.db)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Enumerate HEIC files
    heic_files = sorted(image_dir.rglob("*.HEIC")) + sorted(image_dir.rglob("*.heic"))
    heic_files = sorted(set(heic_files))
    if args.limit:
        heic_files = heic_files[: args.limit]

    total = len(heic_files)
    print(f"Found {total} HEIC files under {image_dir}")

    # Load checkpoint
    checkpoint = load_checkpoint(checkpoint_path)

    # With --retry-errors, treat any checkpointed image that is NOT in the
    # output CSV as a previous failure and drop it so it reprocesses. (Older
    # runs checkpointed failures too, leaving them stuck.)
    if args.retry_errors and checkpoint:
        succeeded = _image_paths_in_csv(output_path)
        retryable = {p for p in checkpoint if p not in succeeded}
        if retryable:
            checkpoint -= retryable
            print(f"  retry-errors: {len(retryable)} previously-failed images requeued")

    pending = [p for p in heic_files if str(p) not in checkpoint]
    print(f"  {len(checkpoint)} already processed, {len(pending)} remaining")

    if not pending:
        print("Nothing to do.")
        return

    # Load sites for fuzzy matching
    sites = load_sites(db_path)
    print(f"  {len(sites)} sites loaded for location matching")

    # Open CSV (append so restarts don't lose data)
    write_header = not output_path.exists() or output_path.stat().st_size == 0
    csv_file = output_path.open("a", newline="")
    writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDNAMES)
    if write_header:
        writer.writeheader()

    client = anthropic.AsyncAnthropic(api_key=api_key)
    semaphore = asyncio.Semaphore(args.concurrency)

    done = 0
    errors = 0
    checkpoint_dirty = 0

    async def process_one(heic_path: Path) -> None:
        nonlocal done, errors, checkpoint_dirty
        fields = await extract_fields(client, semaphore, heic_path, args.model)
        if not fields:
            errors += 1
            # With --retry-errors, do not checkpoint failed extractions so a
            # later run reprocesses them. (Default keeps prior behaviour.)
            if not args.retry_errors:
                checkpoint.add(str(heic_path))
        else:
            row = build_row(heic_path, fields, sites)
            writer.writerow(row)
            csv_file.flush()
            checkpoint.add(str(heic_path))
        done += 1
        checkpoint_dirty += 1
        if checkpoint_dirty >= 25:
            save_checkpoint(checkpoint_path, checkpoint)
            checkpoint_dirty = 0
        if not HAS_TQDM and done % 50 == 0:
            print(f"  {done}/{len(pending)} processed ({errors} errors)")

    tasks = [process_one(p) for p in pending]

    if HAS_TQDM:
        await async_tqdm.gather(*tasks, desc="Extracting", total=len(tasks), unit="img")
    else:
        await asyncio.gather(*tasks)

    # Final checkpoint flush
    save_checkpoint(checkpoint_path, checkpoint)
    csv_file.close()

    print(f"\nDone. {done} processed, {errors} errors.")
    print(f"Output: {output_path}")
    print(f"Checkpoint: {checkpoint_path}")
    print(f"\nNext step: python3 server/ingestion/ingest_data.py --db server/priis.db")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract FR24 telemetry from HEIC screenshots via Claude vision")
    parser.add_argument("--image-dir",   default=str(DEFAULT_IMAGE_DIR), help="Directory containing HEIC files")
    parser.add_argument("--output",      default=str(DEFAULT_OUTPUT),    help="Output CSV path")
    parser.add_argument("--db",          default=str(DEFAULT_DB),        help="priis.db for site mapping")
    parser.add_argument("--checkpoint",  default=str(DEFAULT_CHECKPOINT),help="Checkpoint JSON path")
    parser.add_argument("--limit",       type=int, default=0,            help="Process only first N images (0=all)")
    parser.add_argument("--retry-errors", action="store_true",           help="Reprocess images whose extraction previously failed (don't checkpoint failures)")
    parser.add_argument("--model",       default="claude-haiku-4-5-20251001", help="Claude model to use")
    parser.add_argument("--concurrency", type=int, default=5,            help="Parallel API calls")
    args = parser.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
