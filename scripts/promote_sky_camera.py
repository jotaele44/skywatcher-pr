#!/usr/bin/env python3
"""Promote an approved community camera suggestion into the tracked catalog.

    python3 scripts/promote_sky_camera.py <submission_id> [--lat 18.5 --lon -67.1] [--id my-cam-id]

Only approved ``camera_link`` and ``video_link`` submissions can be promoted.
Uploaded clips stay in the runtime store and are never committed to git. The
new entry is link-out only (``embed: null``) unless ``--youtube`` or ``--vimeo``
passes a video id whose owner allows embedding. The catalog is re-validated against
schemas/sky_camera.schema.json before it is written.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from skywatcher.core.cameras import SubmissionStore  # noqa: E402
from skywatcher.core.cameras.validation import normalize_text  # noqa: E402

CATALOG = ROOT / "data" / "reference" / "sky_cameras" / "cameras.v1.json"
SCHEMA = ROOT / "schemas" / "sky_camera.schema.json"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize_text(text)).strip("-")[:80] or "camera"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("submission_id")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--id", dest="camera_id")
    parser.add_argument("--provider")
    parser.add_argument("--youtube", help="video id, only if the owner allows embedding")
    parser.add_argument("--vimeo", help="video id, only if the owner allows embedding")
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path(os.environ.get("SKYWATCHER_SKY_CAMERAS_ROOT", ROOT / "data" / "sky_cameras")),
    )
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    args = parser.parse_args(argv)

    row = SubmissionStore(args.runtime_root).get(args.submission_id)
    if row is None:
        parser.error("no such submission")
    if row["status"] != "approved":
        parser.error(f"submission is {row['status']}; approve it first")
    if row["kind"] not in ("camera_link", "video_link"):
        parser.error("uploaded clips stay in the runtime store and are not promoted into git")
    lat = args.lat if args.lat is not None else row["lat"]
    lon = args.lon if args.lon is not None else row["lon"]
    if lat is None or lon is None or not row["municipality"]:
        parser.error("the catalog needs a municipality and --lat/--lon")

    data = json.loads(args.catalog.read_text(encoding="utf-8"))
    camera_id = args.camera_id or _slug(f"{row['municipality']} {row['title']}")
    if any(camera["id"] == camera_id for camera in data["cameras"]):
        parser.error(f"id {camera_id} already exists; pass --id")
    embed = None
    if args.youtube:
        embed = {"kind": "youtube", "video_id": args.youtube}
    elif args.vimeo:
        embed = {"kind": "vimeo", "video_id": args.vimeo}
    entry = {
        "id": camera_id,
        "name": row["title"],
        "categories": row["categories"],
        "municipality": row["municipality"],
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "provider": args.provider or "Community suggestion",
        "page_url": row["url"],
        "embed": embed,
        "terms_note": f"Suggested by the community (submission {row['id'][:12]}); verify the owner's terms before embedding.",
        "source_url": row["url"],
        "verified_at": date.today().isoformat(),
        "last_known_status": "unknown",
        "added_by": "community",
    }
    data["cameras"].append(entry)

    try:
        import jsonschema

        jsonschema.validate(data, json.loads(SCHEMA.read_text(encoding="utf-8")))
    except ImportError:
        print("warning: jsonschema not installed; run pytest tests/test_sky_cameras_catalog.py", file=sys.stderr)
    args.catalog.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"added {camera_id} to {args.catalog}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
