"""
FR24 SIDECAR RECONCILIATION

Read-only Google Photos Takeout sidecar reconciliation for timestamp-renamed
FR24 screenshots. This module does not OCR images and does not mutate source
files. It links screenshots to supplemental-metadata JSON using image filename
timestamps and Google Takeout photoTakenTime/creationTime timestamps.

Outputs:
  - fr24_sidecar_reconciliation_candidates.csv
  - fr24_sidecar_reconciliation_summary.json
  - fr24_sidecar_reconciliation_resolved.csv
  - fr24_manifest_with_sidecars.csv
  - fr24_sidecar_review_queue.csv
  - fr24_sidecar_reconciliation_resolved_summary.json
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

IMAGE_EXTS = {".png", ".heic", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
DEFAULT_TZ = "America/Puerto_Rico"

DATE_NAME_RE = re.compile(
    r"(?P<y>20\d{2})-(?P<m>\d{2})-(?P<d>\d{2})[ _-]+(?P<h>\d{2})-(?P<mi>\d{2})-(?P<s>\d{2})",
    re.I,
)


def _tz(name: str):
    if ZoneInfo is None:
        return timezone.utc
    return ZoneInfo(name)


def image_dt_from_name(path: Path, tz_name: str = DEFAULT_TZ) -> Optional[datetime]:
    m = DATE_NAME_RE.search(path.stem)
    if not m:
        return None
    g = {k: int(v) for k, v in m.groupdict().items()}
    return datetime(g["y"], g["m"], g["d"], g["h"], g["mi"], g["s"], tzinfo=_tz(tz_name))


def parse_google_time(obj: object, tz_name: str = DEFAULT_TZ) -> Optional[datetime]:
    if not isinstance(obj, dict):
        return None
    ts = obj.get("timestamp")
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(_tz(tz_name))
    except Exception:
        return None


def load_sidecar(path: Path, tz_name: str = DEFAULT_TZ) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"path": path, "error": repr(exc)}
    return {
        "path": path,
        "title": data.get("title"),
        "description": data.get("description"),
        "photo_dt": parse_google_time(data.get("photoTakenTime"), tz_name),
        "creation_dt": parse_google_time(data.get("creationTime"), tz_name),
        "geoData": data.get("geoData"),
        "geoDataExif": data.get("geoDataExif"),
        "error": "",
    }


def iter_images(root: Path) -> List[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


def iter_sidecars(root: Path) -> List[Path]:
    return sorted(p for p in root.rglob("*.json") if p.is_file())


def _kind_priority(kind: str) -> int:
    return 0 if kind == "photo_dt" else 1


def _image_duplicate_priority(name: str) -> int:
    return 1 if "_1." in name else 0


def _pair_sort_key(pair: dict) -> tuple:
    image = pair["image"]
    return (
        pair["delta_seconds"],
        _kind_priority(pair["sidecar_time_kind"]),
        _image_duplicate_priority(image["name"]),
        image["name"],
        pair["sidecar_path"],
    )


def _best_pair_for_sidecar(existing: Optional[dict], candidate: dict) -> dict:
    if existing is None:
        return candidate
    return candidate if _pair_sort_key(candidate) < _pair_sort_key(existing) else existing


def build_candidate_rows(root: Path, max_delta_seconds: int = 300, tz_name: str = DEFAULT_TZ) -> Tuple[List[dict], dict]:
    """Build sidecar candidate rows with global one-to-one assignment.

    A naive nearest-neighbor pass can collapse many screenshots onto the first
    sidecar that shares the same timestamp. This function instead creates all
    candidate image/sidecar pairs inside the time window, sorts them by match
    quality, and greedily assigns one sidecar to one image. Images that had a
    plausible candidate but lost the one-to-one assignment are routed to review
    as sidecar conflicts.
    """

    images = [
        {"path": p, "name": p.name, "dt_name": image_dt_from_name(p, tz_name), "suffix": p.suffix.lower()}
        for p in iter_images(root)
    ]
    sidecars = [load_sidecar(p, tz_name) for p in iter_sidecars(root)]

    sidecar_times: List[Tuple[float, str, dict, str]] = []
    for sidecar in sidecars:
        for kind in ("photo_dt", "creation_dt"):
            dt = sidecar.get(kind)
            if dt:
                sidecar_times.append((dt.timestamp(), kind, sidecar, dt.isoformat()))
    sidecar_times.sort(key=lambda x: (x[0], _kind_priority(x[1]), str(x[2].get("path", ""))))
    time_values = [x[0] for x in sidecar_times]

    all_pairs: List[dict] = []
    best_rejected_by_image: Dict[int, dict] = {}

    for image_index, image in enumerate(images):
        img_dt = image["dt_name"]
        if not img_dt:
            continue
        img_ts = img_dt.timestamp()
        lo = bisect.bisect_left(time_values, img_ts - max_delta_seconds)
        hi = bisect.bisect_right(time_values, img_ts + max_delta_seconds)

        # Keep only the best time-kind candidate per sidecar for this image.
        best_by_sidecar: Dict[str, dict] = {}
        for side_ts, kind, sidecar, side_iso in sidecar_times[lo:hi]:
            sidecar_path = str(sidecar["path"])
            pair = {
                "image_index": image_index,
                "image": image,
                "delta_seconds": round(abs(img_ts - side_ts), 3),
                "sidecar_time_kind": kind,
                "sidecar_path": sidecar_path,
                "sidecar_title": sidecar.get("title") or "",
                "sidecar_time_pr": side_iso,
            }
            best_by_sidecar[sidecar_path] = _best_pair_for_sidecar(best_by_sidecar.get(sidecar_path), pair)

        for pair in best_by_sidecar.values():
            all_pairs.append(pair)
            existing = best_rejected_by_image.get(image_index)
            if existing is None or _pair_sort_key(pair) < _pair_sort_key(existing):
                best_rejected_by_image[image_index] = pair

    selected_by_image: Dict[int, dict] = {}
    used_sidecars = set()
    for pair in sorted(all_pairs, key=_pair_sort_key):
        image_index = pair["image_index"]
        sidecar_path = pair["sidecar_path"]
        if image_index in selected_by_image or sidecar_path in used_sidecars:
            continue
        selected_by_image[image_index] = pair
        used_sidecars.add(sidecar_path)

    rows: List[dict] = []
    for image_index, image in enumerate(images):
        img_dt = image["dt_name"]
        pair = selected_by_image.get(image_index)
        rejected_pair = best_rejected_by_image.get(image_index)
        if pair:
            status = "candidate_match"
            source_pair = pair
        elif rejected_pair:
            status = "candidate_conflict"
            source_pair = rejected_pair
        else:
            status = "unmatched"
            source_pair = None
        rows.append(
            {
                "image_path": str(image["path"]),
                "image_name": image["name"],
                "image_dt_from_name_pr": img_dt.isoformat() if img_dt else "",
                "match_status": status,
                "delta_seconds": "" if source_pair is None else source_pair["delta_seconds"],
                "sidecar_time_kind": "" if source_pair is None else source_pair["sidecar_time_kind"],
                "sidecar_path": "" if source_pair is None else source_pair["sidecar_path"],
                "sidecar_title": "" if source_pair is None else source_pair["sidecar_title"],
                "sidecar_time_pr": "" if source_pair is None else source_pair["sidecar_time_pr"],
            }
        )

    status_counts = Counter(r["match_status"] for r in rows)
    summary = {
        "images": len(images),
        "sidecars": len(sidecars),
        "sidecar_times": len(sidecar_times),
        "candidate_matches_5min": status_counts.get("candidate_match", 0) + status_counts.get("candidate_conflict", 0),
        "primary_candidate_matches": status_counts.get("candidate_match", 0),
        "candidate_conflicts": status_counts.get("candidate_conflict", 0),
        "unmatched": status_counts.get("unmatched", 0),
        "candidate_pair_count": len(all_pairs),
        "unique_sidecars_assigned": len(used_sidecars),
    }
    return rows, summary


def _safe_delta(row: dict) -> float:
    value = row.get("delta_seconds")
    if value is None or value == "":
        return 999999999
    try:
        return float(value)
    except Exception:
        return 999999999


def match_band(delta: float) -> str:
    if delta <= 2:
        return "strong"
    if delta <= 60:
        return "reviewable"
    if delta <= 300:
        return "weak"
    return "unmatched"


def resolve_one_to_one(rows: List[dict]) -> Tuple[List[dict], dict]:
    resolved_rows: List[dict] = []
    for row in rows:
        out = dict(row)
        if row.get("match_status") == "candidate_match" and row.get("sidecar_path"):
            out["resolved_status"] = "matched_primary"
        elif row.get("match_status") == "candidate_conflict" and row.get("sidecar_path"):
            out["resolved_status"] = "sidecar_duplicate_conflict"
        else:
            out["resolved_status"] = "unmatched_metadata_gap"
        out["match_band"] = match_band(_safe_delta(out))
        out["sidecar_conflict_count"] = ""
        out["ocr_status"] = "eligible"

        if out["resolved_status"] == "unmatched_metadata_gap":
            out["review_status"] = "metadata_gap"
        elif out["match_band"] == "weak":
            out["review_status"] = "weak_sidecar_match_review"
        elif out["resolved_status"] == "sidecar_duplicate_conflict":
            out["review_status"] = "sidecar_conflict_review"
        else:
            out["review_status"] = "sidecar_linked"
        resolved_rows.append(out)

    counts = Counter(r["resolved_status"] for r in resolved_rows)
    bands = Counter(r["match_band"] for r in resolved_rows)
    review_counts = Counter(r["review_status"] for r in resolved_rows)
    summary = {
        "total_images": len(resolved_rows),
        "resolved_status_counts": dict(counts),
        "match_band_counts": dict(bands),
        "review_status_counts": dict(review_counts),
        "primary_sidecar_matches": counts.get("matched_primary", 0),
        "metadata_gaps": counts.get("unmatched_metadata_gap", 0),
        "sidecar_duplicate_conflicts": counts.get("sidecar_duplicate_conflict", 0),
    }
    return resolved_rows, summary


def _write_csv(path: Path, rows: List[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def run(root: Path, output_dir: Path, max_delta_seconds: int = 300, tz_name: str = DEFAULT_TZ) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates, summary = build_candidate_rows(root, max_delta_seconds, tz_name)
    candidate_csv = output_dir / "fr24_sidecar_reconciliation_candidates.csv"
    _write_csv(candidate_csv, candidates)
    summary["output_csv"] = str(candidate_csv)
    (output_dir / "fr24_sidecar_reconciliation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    resolved, resolved_summary = resolve_one_to_one(candidates)
    resolved_csv = output_dir / "fr24_sidecar_reconciliation_resolved.csv"
    manifest_csv = output_dir / "fr24_manifest_with_sidecars.csv"
    review_csv = output_dir / "fr24_sidecar_review_queue.csv"
    _write_csv(resolved_csv, resolved)
    _write_csv(manifest_csv, resolved)
    _write_csv(review_csv, [r for r in resolved if r["review_status"] != "sidecar_linked"])
    resolved_summary.update(
        {
            "output_csv": str(resolved_csv),
            "manifest_with_sidecars": str(manifest_csv),
            "review_queue": str(review_csv),
        }
    )
    (output_dir / "fr24_sidecar_reconciliation_resolved_summary.json").write_text(
        json.dumps(resolved_summary, indent=2), encoding="utf-8"
    )
    return resolved_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile timestamp-renamed FR24 screenshots with Google Takeout sidecars")
    parser.add_argument("--root", required=True, help="Screenshot corpus root")
    parser.add_argument("--output-dir", default="data/_manifests/fr24_audit", help="Output manifest directory")
    parser.add_argument("--max-delta-seconds", type=int, default=300)
    parser.add_argument("--timezone", default=DEFAULT_TZ)
    args = parser.parse_args()
    summary = run(Path(args.root), Path(args.output_dir), args.max_delta_seconds, args.timezone)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
