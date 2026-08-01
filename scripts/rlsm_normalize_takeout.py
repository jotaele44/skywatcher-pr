#!/usr/bin/env python3
"""
Normalize a Google Photos Takeout export into the FR24 baseline convention.

Every bucket under data/FR24_baseline follows one rule, decoded from the corpus
and verified against 100 files spanning summer and winter months:

    <photoTakenTime in America/Puerto_Rico>_<sha256(file)[:8]>.<ext lowercased>
    e.g.  2025-08-16T04-02-17_7f148102.png

and the Takeout metadata travels alongside as ``<newname>.sidecar.json``.

Two details that matter:

  * The timestamp is LOCAL, not UTC. Puerto Rico does not observe DST, so the
    offset is a constant -4 — no tzdata lookup, and no summer/winter special
    case. (Verified: an August and a December file both derive correctly.)
  * The hash is over file CONTENT, which is what makes the name idempotent and
    duplicate-revealing: two exports of the same screenshot land on the same
    filename rather than two rows.

A raw export dropped into a bucket does not satisfy the inventory: rel_path,
month_bucket and filename_ts are all derived from this name, so unnormalized
files lose their time dimension and the temporal-wave analysis with it.

CLI:
    python3 scripts/rlsm_normalize_takeout.py --verify data/FR24_baseline/2025-08
    python3 scripts/rlsm_normalize_takeout.py data/FR24_baseline/2026-03
    python3 scripts/rlsm_normalize_takeout.py data/FR24_baseline/2026-03 --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

AST = timezone(timedelta(hours=-4))          # America/Puerto_Rico, no DST
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".heic", ".webp"}
NORMALIZED = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}_[0-9a-f]{8}\.[a-z]+$")
TAKEOUT_SUFFIX = ".supplemental-metadata.json"


def sha8(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:8]


def sidecar_for(img: Path) -> Path | None:
    """
    Locate the metadata for an image.

    Takeout normally writes ``<image><TAKEOUT_SUFFIX>``, and normalized files
    carry ``.sidecar.json``. Takeout also de-duplicates by appending ``(n)`` —
    and it puts the marker on the *base* name of the image while moving it to
    the end of the JSON stem, so ``IMG_6914(1).HEIC`` pairs with
    ``IMG_6914.HEIC.supplemental-metadata(1).json``. Nothing about that is
    guessable from the image name alone, so it gets its own case.
    """
    for cand in (img.with_name(img.name + TAKEOUT_SUFFIX),
                 img.with_name(img.name + ".sidecar.json")):
        if cand.exists():
            return cand
    m = re.match(r"^(?P<stem>.+?)\((?P<n>\d+)\)(?P<ext>\.[^.]+)$", img.name)
    if m:
        cand = img.with_name(f"{m['stem']}{m['ext']}"
                             f".supplemental-metadata({m['n']}).json")
        if cand.exists():
            return cand
    return None


def target_name(img: Path, side: Path) -> str | None:
    try:
        meta = json.loads(side.read_text(encoding="utf-8"))
        ts = int(meta["photoTakenTime"]["timestamp"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError):
        return None
    stamp = datetime.fromtimestamp(ts, AST).strftime("%Y-%m-%dT%H-%M-%S")
    return f"{stamp}_{sha8(img)}{img.suffix.lower()}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--apply", action="store_true", help="rename (default is a dry run)")
    ap.add_argument("--verify", action="store_true",
                    help="re-derive names for already-normalized files and report "
                         "mismatches; touches nothing")
    args = ap.parse_args()

    folder: Path = args.folder
    if not folder.is_dir():
        raise SystemExit(f"not a directory: {folder}")

    planned, already, no_meta, collisions, mismatched = [], 0, [], [], []
    for img in sorted(folder.iterdir()):
        if not img.is_file() or img.name.startswith(".") or img.suffix.lower() == ".json":
            continue
        if img.suffix.lower() not in IMAGE_EXT:
            continue
        side = sidecar_for(img)
        is_norm = bool(NORMALIZED.match(img.name))

        if args.verify:
            if is_norm and side:
                want = target_name(img, side)
                if want and want != img.name:
                    mismatched.append((img.name, want))
            continue

        if is_norm:
            already += 1
            continue
        if side is None:
            no_meta.append(img.name)
            continue
        want = target_name(img, side)
        if want is None:
            no_meta.append(img.name)
            continue
        dest = folder / want
        if dest.exists() and dest != img:
            collisions.append((img.name, want))
            continue
        planned.append((img, side, dest))

    if args.verify:
        checked = sum(1 for p in folder.iterdir()
                      if p.is_file() and NORMALIZED.match(p.name) and sidecar_for(p))
        print(json.dumps({"folder": str(folder), "verifiable": checked,
                          "mismatched": len(mismatched),
                          "examples": mismatched[:5]}, indent=2))
        raise SystemExit(1 if mismatched else 0)

    for img, side, dest in (planned if args.apply else []):
        img.rename(dest)
        side.rename(dest.with_name(dest.name + ".sidecar.json"))

    print(json.dumps({
        "folder": str(folder),
        "mode": "apply" if args.apply else "dry-run",
        "renamed" if args.apply else "would_rename": len(planned),
        "already_normalized": already,
        "no_usable_metadata": len(no_meta),
        "content_duplicates_skipped": len(collisions),
        "examples": [f"{i.name} -> {d.name}" for i, _, d in planned[:4]],
        "no_metadata_examples": no_meta[:4],
        "duplicate_examples": collisions[:4],
    }, indent=2))


if __name__ == "__main__":
    main()
