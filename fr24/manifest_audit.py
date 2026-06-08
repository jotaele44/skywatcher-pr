"""
FR24 MANIFEST AUDIT
Read-only pre-ingest audit for Google Photos Takeout FR24 screenshots.

Supports:
  1. Single FR24 folder audit
  2. Discovery of all */Google Photos/FR24 shards under a parent root
  3. Combined multi-shard corpus audit
  4. Fuzzy Google Takeout sidecar pairing

OCR and DB build remain frozen until the combined corpus audit passes.
"""

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

FR24_ROOT = "/Users/jotaele/Documents/GitHub/Raw Flight Logs/Takeout-9/Google Photos/FR24"
RAW_ROOT = "/Users/jotaele/Documents/GitHub/Raw Flight Logs"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif", ".heic"}
SIDECAR_EXTS = {".json"}
DB_EXTS = {".db", ".sqlite", ".sqlite3"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}
AUDIT_CSV = "fr24_manifest_audit.csv"
AUDIT_JSON = "fr24_manifest_audit_report.json"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _image_dims(path: Path) -> Tuple[Optional[int], Optional[int], bool]:
    try:
        from PIL import Image
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            return img.size[0], img.size[1], False
    except ImportError:
        return None, None, False
    except Exception:
        return None, None, True


def _norm_name(name: str) -> str:
    lowered = name.lower()
    for marker in (
        ".supplemental-metadata.json",
        ".supplemental-metada.json",
        ".supplemental.json",
        ".json",
    ):
        if lowered.endswith(marker):
            lowered = lowered[: -len(marker)]
            break
    for ext in IMAGE_EXTS:
        if lowered.endswith(ext):
            lowered = lowered[: -len(ext)]
            break
    return lowered.replace(" ", "").replace("_", "").replace("-", "")


def _sidecar_candidates(image_path: Path) -> List[str]:
    stem = image_path.stem
    name = image_path.name
    return [
        name + ".supplemental-metadata.json",
        name + ".supplemental-metada.json",
        stem + ".supplemental-metadata.json",
        stem + ".supplemental-metada.json",
        name + ".json",
        stem + ".json",
    ]


def _build_sidecar_index(sidecar_files: Iterable[Path]) -> Dict[Path, Dict[str, Path]]:
    by_dir_exact: Dict[Path, Dict[str, Path]] = {}
    by_dir_norm: Dict[Path, Dict[str, Path]] = {}
    for p in sidecar_files:
        by_dir_exact.setdefault(p.parent, {})[p.name.lower()] = p
        by_dir_norm.setdefault(p.parent, {})[_norm_name(p.name)] = p
    return {"exact": by_dir_exact, "norm": by_dir_norm}  # type: ignore[return-value]


def _find_sidecar(image_path: Path, sidecar_index: Dict[str, Dict[Path, Dict[str, Path]]]) -> Optional[Path]:
    exact = sidecar_index.get("exact", {}).get(image_path.parent, {})
    for candidate in _sidecar_candidates(image_path):
        hit = exact.get(candidate.lower())
        if hit:
            return hit
    norm = sidecar_index.get("norm", {}).get(image_path.parent, {})
    return norm.get(_norm_name(image_path.name))


def _discover_fr24_folders(root: Path) -> List[Path]:
    if root.name == "FR24" and root.is_dir():
        return [root]
    return sorted(p for p in root.rglob("FR24") if p.is_dir() and p.parent.name == "Google Photos")


def _collect_files(roots: List[Path]) -> List[Path]:
    files: List[Path] = []
    for r in roots:
        files.extend(p for p in r.rglob("*") if p.is_file())
    return sorted(files)


def _common_base(roots: List[Path]) -> Path:
    if len(roots) == 1:
        return roots[0]
    try:
        return Path(Path(*Path(str(roots[0])).parts[:1])) if False else Path(__import__("os").path.commonpath([str(r) for r in roots]))
    except Exception:
        return roots[0].parent


def _find_git_tracked_raw(root: Path) -> List[str]:
    try:
        probe = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if probe.returncode != 0:
            return []
        repo_root = Path(probe.stdout.strip())
        listed = subprocess.run(["git", "-C", str(repo_root), "ls-files", "--", str(root)], capture_output=True, text=True)
        if listed.returncode != 0 or not listed.stdout.strip():
            return []
        raw_exts = IMAGE_EXTS | SIDECAR_EXTS | VIDEO_EXTS | DB_EXTS
        return [line for line in listed.stdout.splitlines() if Path(line).suffix.lower() in raw_exts]
    except Exception:
        return []


def discover(root: str, json_only: bool = False) -> dict:
    base = Path(root).expanduser().resolve()
    folders = _discover_fr24_folders(base)
    rows = []
    for folder in folders:
        imgs = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
        jsons = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in SIDECAR_EXTS]
        rows.append({"folder": str(folder), "images": len(imgs), "json_sidecars": len(jsons)})
    report = {"generated_at": _utc_now(), "root": str(base), "fr24_folder_count": len(folders), "folders": rows, "total_images": sum(r["images"] for r in rows), "total_json_sidecars": sum(r["json_sidecars"] for r in rows)}
    if json_only:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"[DISCOVER] Root: {base}")
        print(f"[DISCOVER] FR24 folders: {len(folders)}")
        for r in rows:
            print(f"  {r['images']:>6} images | {r['json_sidecars']:>6} json | {r['folder']}")
        print(f"[DISCOVER] Total images: {report['total_images']}")
    return report


def audit(fr24_dir: str, output_dir: Optional[str] = None, max_images: Optional[int] = None, no_hash: bool = False, json_only: bool = False, combined: bool = False) -> dict:
    started = time.perf_counter()
    root = Path(fr24_dir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"[ERROR] Directory not found or not a directory: {fr24_dir}", file=sys.stderr)
        sys.exit(1)

    roots = _discover_fr24_folders(root) if combined else [root]
    if combined and not roots:
        print(f"[ERROR] No */Google Photos/FR24 folders found under: {root}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(output_dir).expanduser().resolve() if output_dir else (_common_base(roots) if combined else root)
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_mode = "smoke" if max_images else ("combined" if combined else "full")

    if not json_only:
        print(f"[AUDIT] Scanning: {root}")
        print(f"[AUDIT] Output:   {out_dir}")
        print(f"[AUDIT] Mode:     {audit_mode}")
        if combined:
            print(f"[AUDIT] Shards:   {len(roots)}")
        print()

    all_files = _collect_files(roots)
    image_files_all = sorted(p for p in all_files if p.suffix.lower() in IMAGE_EXTS)
    sidecar_files = sorted(p for p in all_files if p.suffix.lower() in SIDECAR_EXTS)
    db_files = sorted(p for p in all_files if p.suffix.lower() in DB_EXTS)
    video_files = sorted(p for p in all_files if p.suffix.lower() in VIDEO_EXTS)
    known_exts = IMAGE_EXTS | SIDECAR_EXTS | DB_EXTS | VIDEO_EXTS
    other_files = sorted(p for p in all_files if p.suffix.lower() not in known_exts)

    full_image_count = len(image_files_all)
    image_files = image_files_all[:max_images] if max_images else image_files_all
    total_images = len(image_files)
    ext_counts = Counter(p.suffix.lower() for p in image_files)
    sidecar_index = _build_sidecar_index(sidecar_files)

    images_with_sidecar: List[Path] = []
    images_without_sidecar: List[Path] = []
    sidecar_lookup: Dict[Path, Optional[Path]] = {}
    for p in image_files:
        hit = _find_sidecar(p, sidecar_index)
        sidecar_lookup[p] = hit
        if hit:
            images_with_sidecar.append(p)
        else:
            images_without_sidecar.append(p)

    if not json_only:
        print(f"  Images found:   {total_images}")
        if max_images or combined:
            print(f"  Full image set: {full_image_count}")
        print(f"  JSON sidecars:  {len(sidecar_files)}")
        print(f"  Video files:    {len(video_files)}")
        print(f"  DB files:       {len(db_files)}  {'← WARNING: unexpected' if db_files else ''}")
        print(f"  Other files:    {len(other_files)}")
        print(f"\n  Extension mix:  {dict(ext_counts)}")
        print(f"\n  With sidecar:   {len(images_with_sidecar)}")
        print(f"  No sidecar:     {len(images_without_sidecar)}")
        print(f"\n  Scanning {total_images} images ({'dimensions' if no_hash else 'SHA-256 + dimensions'}) …")

    records: List[dict] = []
    hash_index: Dict[str, str] = {}
    corrupt_count = 0
    dupe_count = 0
    base_for_rel = _common_base(roots)

    for i, path in enumerate(image_files, 1):
        if not json_only and (i % 500 == 0 or i == total_images):
            print(f"    {i}/{total_images} …", end="\r")
        sha = None if no_hash else _sha256(path)
        w, h, is_corrupt = _image_dims(path)
        corrupt_count += int(is_corrupt)
        is_dupe = False
        dupe_of = None
        if sha:
            if sha in hash_index:
                is_dupe = True
                dupe_of = hash_index[sha]
                dupe_count += 1
            else:
                hash_index[sha] = str(path)
        try:
            rel_folder = str(path.parent.relative_to(base_for_rel))
        except ValueError:
            rel_folder = str(path.parent)
        records.append({
            "path": str(path),
            "filename": path.name,
            "folder": rel_folder,
            "size_bytes": path.stat().st_size,
            "sha256": sha,
            "width": w,
            "height": h,
            "is_corrupt": is_corrupt,
            "is_duplicate": is_dupe,
            "duplicate_of": dupe_of,
            "has_sidecar": sidecar_lookup[path] is not None,
            "sidecar_path": str(sidecar_lookup[path]) if sidecar_lookup[path] else "",
            "scanned_at": _utc_now(),
        })

    valid = total_images - corrupt_count - dupe_count
    git_tracked_raw: List[str] = []
    for r in roots:
        git_tracked_raw.extend(_find_git_tracked_raw(r))
    git_tracked_raw = sorted(set(git_tracked_raw))

    csv_path = out_dir / AUDIT_CSV
    fields = ["path", "filename", "folder", "size_bytes", "sha256", "width", "height", "is_corrupt", "is_duplicate", "duplicate_of", "has_sidecar", "sidecar_path", "scanned_at"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

    total_bytes = sum(r["size_bytes"] for r in records)
    report = {
        "generated_at": _utc_now(),
        "audit_mode": audit_mode,
        "combined": combined,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "input_root": str(root),
        "fr24_roots": [str(r) for r in roots],
        "fr24_folder_count": len(roots),
        "output_dir": str(out_dir),
        "full_image_count": full_image_count,
        "total_images": total_images,
        "valid_unique": valid,
        "corrupt": corrupt_count,
        "duplicates": dupe_count,
        "json_sidecars": len(sidecar_files),
        "images_with_sidecar": len(images_with_sidecar),
        "images_without_sidecar": len(images_without_sidecar),
        "sample_images_without_sidecar": [str(p) for p in images_without_sidecar[:10]],
        "video_files": len(video_files),
        "db_files_in_tree": [str(p) for p in db_files],
        "git_tracked_raw_files": git_tracked_raw,
        "other_files": [str(p) for p in other_files[:50]],
        "total_size_bytes": total_bytes,
        "total_size_gb": round(total_bytes / 1e9, 3),
        "extension_counts": dict(sorted(ext_counts.items())),
        "manifest_csv": str(csv_path),
        "no_hash": no_hash,
        "audit_pass": corrupt_count == 0 and len(db_files) == 0 and len(git_tracked_raw) == 0,
    }

    json_path = out_dir / AUDIT_JSON
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    if json_only:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"\n  Corrupt:        {corrupt_count}")
        print(f"  Duplicates:     {dupe_count}")
        print(f"  Valid unique:   {valid}")
        print("\n  Git-tracked raw files: none ✓" if not git_tracked_raw else f"\n  [WARNING] Git-tracked raw files: {len(git_tracked_raw)}")
        print(f"\n  Manifest CSV:   {csv_path}")
        print(f"  Audit report:   {json_path}")
        print(f"\n  ══ AUDIT {'PASS' if report['audit_pass'] else 'FAIL'} ══")
        if report["audit_pass"]:
            print("    0 corrupt  |  0 DB files  |  0 git-tracked raw files")
            print("    Ready to proceed to OCR pipeline planning after coverage review.")
        else:
            print("    Fix corrupt files, stray DB files, or git-tracked raw files before OCR.")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="FR24 Google Photos Takeout manifest audit")
    parser.add_argument("fr24_dir", nargs="?", help="Path to FR24 folder or parent raw root")
    parser.add_argument("--root", metavar="DIR", help="Path to FR24 folder or parent raw root; overrides positional path")
    parser.add_argument("--output-dir", metavar="DIR", help="Directory to write CSV + JSON report")
    parser.add_argument("--max-images", type=int, metavar="N", help="Limit scan to first N images")
    parser.add_argument("--no-hash", action="store_true", help="Skip SHA-256 hashing for faster count/dimension audit")
    parser.add_argument("--json-only", action="store_true", help="Print only the JSON report to stdout")
    parser.add_argument("--discover-fr24-folders", action="store_true", help="List all */Google Photos/FR24 folders under root and exit")
    parser.add_argument("--combined", action="store_true", help="Audit all discovered */Google Photos/FR24 folders as one corpus")
    args = parser.parse_args()

    root = args.root or args.fr24_dir or FR24_ROOT
    if args.discover_fr24_folders:
        report = discover(root, args.json_only)
        sys.exit(0 if report["fr24_folder_count"] else 1)
    report = audit(root, args.output_dir, args.max_images, args.no_hash, args.json_only, args.combined)
    sys.exit(0 if report["audit_pass"] else 1)


if __name__ == "__main__":
    main()
