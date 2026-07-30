"""Materialize deterministic image crops for every detected map/GUI icon."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - explicit runtime failure
    Image = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUT_ROOT = REPO / "outputs" / "icon_library"
MANIFEST = REPO / "outputs" / "icon_library_manifest.jsonl"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS icon_artifacts (
    icon_artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    icon_id INTEGER NOT NULL UNIQUE REFERENCES icon_observations(icon_id),
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    source_sha256 TEXT NOT NULL,
    crop_rel_path TEXT,
    crop_sha256 TEXT,
    capture_status TEXT NOT NULL,
    capture_error TEXT,
    method TEXT NOT NULL,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_icon_artifact_screenshot
    ON icon_artifacts(screenshot_id);
CREATE INDEX IF NOT EXISTS ix_icon_artifact_status
    ON icon_artifacts(capture_status);
"""

METHOD = "bbox_original_rgb_v1"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned[:80] or "unnamed"


def _portable_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _resolve_source(rel_path: str, filename: str, image_root: Path | None) -> Path | None:
    candidates = [REPO / rel_path]
    if image_root is not None:
        candidates.extend((image_root / rel_path, image_root / filename))
        baseline_prefix = "data/FR24_baseline/"
        if rel_path.startswith(baseline_prefix):
            candidates.append(image_root / rel_path[len(baseline_prefix):])
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _output_path(icon_id: int, source_sha256: str, cluster_id: int | None, icon_class: str | None) -> Path:
    if cluster_id is not None:
        group = f"cluster_{cluster_id:04d}"
    elif icon_class:
        group = f"class_{_safe_component(icon_class)}"
    else:
        group = "unclustered"
    return OUT_ROOT / group / f"icon_{icon_id:08d}_{source_sha256[:12]}.png"


def _capture_one(row: sqlite3.Row, *, image_root: Path | None, padding: int) -> dict[str, Any]:
    base = {
        "icon_id": int(row["icon_id"]), "screenshot_id": int(row["screenshot_id"]),
        "source_sha256": str(row["sha256"]), "source_rel_path": str(row["rel_path"]),
        "cluster_id": row["cluster_id"], "icon_class": row["icon_class"],
        "bbox": [row["bbox_x"], row["bbox_y"], row["bbox_w"], row["bbox_h"]],
        "method": METHOD,
    }
    if Image is None or ImageOps is None:
        return {**base, "capture_status": "failed", "capture_error": "pillow_not_installed"}
    source = _resolve_source(str(row["rel_path"]), str(row["filename"]), image_root)
    if source is None:
        return {**base, "capture_status": "failed", "capture_error": "source_image_missing"}
    try:
        x, y = int(row["bbox_x"]), int(row["bbox_y"])
        width, height = int(row["bbox_w"]), int(row["bbox_h"])
    except (TypeError, ValueError):
        return {**base, "capture_status": "failed", "capture_error": "invalid_bbox"}
    if width <= 0 or height <= 0:
        return {**base, "capture_status": "failed", "capture_error": "empty_bbox"}
    try:
        with Image.open(source) as image:
            image.load()
            image = ImageOps.exif_transpose(image).convert("RGBA")
            image_width, image_height = image.size
            x0, y0 = max(0, x-padding), max(0, y-padding)
            x1, y1 = min(image_width, x+width+padding), min(image_height, y+height+padding)
            if x1 <= x0 or y1 <= y0:
                return {**base, "capture_status": "failed", "capture_error": "bbox_outside_image"}
            crop = image.crop((x0, y0, x1, y1))
            output = _output_path(
                int(row["icon_id"]), str(row["sha256"]),
                int(row["cluster_id"]) if row["cluster_id"] is not None else None,
                str(row["icon_class"]) if row["icon_class"] else None,
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            crop.save(output, format="PNG", optimize=False, compress_level=9)
        crop_sha = hashlib.sha256(output.read_bytes()).hexdigest()
        return {
            **base, "capture_status": "ok", "capture_error": None,
            "crop_rel_path": _portable_path(output), "crop_sha256": crop_sha,
            "crop_width": crop.size[0], "crop_height": crop.size[1],
            "padded_bbox": [x0, y0, x1-x0, y1-y0],
        }
    except Exception as exc:
        return {**base, "capture_status": "failed", "capture_error": f"{type(exc).__name__}: {exc}"[:500]}


def _write_manifest(conn: sqlite3.Connection, path: Path) -> int:
    rows = conn.execute(
        """SELECT a.icon_id, a.screenshot_id, a.source_sha256, a.crop_rel_path,
                  a.crop_sha256, a.capture_status, a.capture_error, a.method,
                  a.observed_at, i.cluster_id, i.icon_class, i.bbox_x, i.bbox_y,
                  i.bbox_w, i.bbox_h
           FROM icon_artifacts a JOIN icon_observations i ON i.icon_id=a.icon_id
           ORDER BY a.icon_id"""
    ).fetchall()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            record = {
                "icon_id": row[0], "screenshot_id": row[1], "source_sha256": row[2],
                "crop_rel_path": row[3], "crop_sha256": row[4],
                "capture_status": row[5], "capture_error": row[6], "method": row[7],
                "observed_at": row[8], "cluster_id": row[9], "icon_class": row[10],
                "bbox": [row[11], row[12], row[13], row[14]],
            }
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False)+"\n")
    return len(rows)


def run(db_path: Path = DB, *, image_root: Path | None = None, output_root: Path = OUT_ROOT, manifest_path: Path = MANIFEST, padding: int = 2, limit: int = 0) -> dict[str, Any]:
    global OUT_ROOT
    OUT_ROOT = output_root
    if not db_path.exists():
        raise FileNotFoundError(f"RLSM DB not found: {db_path}")
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    ensure_schema(conn)
    sql = """SELECT i.icon_id, i.screenshot_id, i.bbox_x, i.bbox_y,
                    i.bbox_w, i.bbox_h, i.cluster_id, i.icon_class,
                    s.sha256, s.rel_path, s.filename
             FROM icon_observations i JOIN screenshots s ON s.screenshot_id=i.screenshot_id
             ORDER BY i.icon_id"""
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()
    ok = failed = 0
    for row in rows:
        result = _capture_one(row, image_root=image_root, padding=max(0, padding))
        observed_at = _iso_now()
        with conn:
            conn.execute(
                """INSERT INTO icon_artifacts
                   (icon_id, screenshot_id, source_sha256, crop_rel_path,
                    crop_sha256, capture_status, capture_error, method, observed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(icon_id) DO UPDATE SET
                       screenshot_id=excluded.screenshot_id,
                       source_sha256=excluded.source_sha256,
                       crop_rel_path=excluded.crop_rel_path,
                       crop_sha256=excluded.crop_sha256,
                       capture_status=excluded.capture_status,
                       capture_error=excluded.capture_error,
                       method=excluded.method, observed_at=excluded.observed_at""",
                (result["icon_id"], result["screenshot_id"], result["source_sha256"],
                 result.get("crop_rel_path"), result.get("crop_sha256"),
                 result["capture_status"], result.get("capture_error"), METHOD, observed_at),
            )
        if result["capture_status"] == "ok":
            ok += 1
        else:
            failed += 1
    manifest_rows = _write_manifest(conn, manifest_path)
    conn.close()
    return {
        "targets": len(rows), "captured": ok, "failed": failed,
        "manifest_rows": manifest_rows, "manifest": manifest_path.as_posix(),
        "output_root": output_root.as_posix(), "method": METHOD,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--image-root", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=OUT_ROOT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--padding", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        result = run(args.db, image_root=args.image_root, output_root=args.output_root,
                     manifest_path=args.manifest, padding=args.padding, limit=args.limit)
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
