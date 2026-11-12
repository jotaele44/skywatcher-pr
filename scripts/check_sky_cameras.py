#!/usr/bin/env python3
"""Check whether each curated Sky Camera is reachable and live, and record the result.

    python3 scripts/check_sky_cameras.py                  # writes data/sky_cameras/status.json
    python3 scripts/check_sky_cameras.py --write-catalog  # also refreshes verified_at /
                                                          # last_known_status in cameras.v1.json

A camera is ``online`` when its page answers 200 and does not carry its provider's
offline marker, and (for an embedded stream) YouTube/Vimeo oEmbed still answers for
it. A 4xx/5xx answer or an offline marker is ``offline``; a network error or a site
that refuses automated clients is ``unknown``, because we cannot tell. The API merges
status.json in at read time. This needs network access, so it is a manual step, not CI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "reference" / "sky_cameras" / "cameras.v1.json"
USER_AGENT = "Mozilla/5.0 (compatible; skywatcher-pr camera checker)"
OFFLINE_MARKERS = (b"<strong>OFFLINE</strong>",)
OEMBED = {
    "youtube": "https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/watch?v={video_id}",
    "vimeo": "https://vimeo.com/api/oembed.json?url=https://vimeo.com/{video_id}",
}


def _fetch(url: str, timeout: float) -> tuple[int | None, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - https only
            return response.status, response.read(2_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, b""


def check_camera(camera: dict, timeout: float = 20.0) -> dict:
    code, body = _fetch(camera["page_url"], timeout)
    if code is None or code in (401, 403, 429):
        status = "unknown"  # unreachable, or the site refuses automated clients
    elif code >= 400 or any(marker in body for marker in OFFLINE_MARKERS):
        status = "offline"
    else:
        status = "online"
    embed = camera.get("embed")
    embed_code = None
    if embed and embed.get("kind") in OEMBED:
        embed_code, _ = _fetch(OEMBED[embed["kind"]].format(video_id=embed["video_id"]), timeout)
        if embed_code != 200:
            status = "offline"
    return {
        "status": status,
        "http_status": code,
        "embed_http_status": embed_code,
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path(os.environ.get("SKYWATCHER_SKY_CAMERAS_ROOT", ROOT / "data" / "sky_cameras")),
    )
    parser.add_argument("--write-catalog", action="store_true", help="refresh verified_at/last_known_status")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)

    data = json.loads(args.catalog.read_text(encoding="utf-8"))
    results: dict[str, dict] = {}
    for camera in data["cameras"]:
        result = check_camera(camera, args.timeout)
        results[camera["id"]] = result
        print(f"{result['status']:8} {result['http_status']!s:>4}  {camera['id']}")
        if args.write_catalog and result["status"] != "unknown":
            camera["last_known_status"] = result["status"]
            camera["verified_at"] = result["checked_at"][:10]

    args.runtime_root.mkdir(parents=True, exist_ok=True)
    out = args.runtime_root / "status.json"
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    out.write_text(json.dumps({"checked_at": stamp, "cameras": results}, indent=2) + "\n", encoding="utf-8")
    if args.write_catalog:
        args.catalog.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = {name: sum(r["status"] == name for r in results.values()) for name in ("online", "offline", "unknown")}
    print(f"wrote {out}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
