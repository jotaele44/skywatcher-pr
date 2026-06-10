"""
SCREENSHOT INVENTORY
Scans a directory of FR24 screenshots and builds a full manifest with
SHA-256 hashes, image dimensions, corrupt detection, and duplicate flagging.
Produces both an in-memory record list and an on-disk CSV report.
"""

import csv
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif", ".heic"}

MANIFEST_FIELDS = [
    "path", "filename", "size_bytes", "sha256",
    "width", "height", "is_corrupt", "is_duplicate",
    "duplicate_of", "scanned_at",
]


class ScreenshotInventory:
    """
    Scans a directory of FR24 screenshots and produces a full manifest
    with SHA-256 hashes, dimensions, corrupt flags, and duplicate detection.

    SHA-256 is used as the content-addressed identifier, consistent with
    the screenshot_id scheme used in FlightDatabase.store_screenshot().
    """

    def __init__(self, images_dir: str, db_path: Optional[str] = None):
        self.images_dir = Path(images_dir)
        self.db_path = db_path
        self._manifest: List[dict] = []
        self._hash_index: Dict[str, str] = {}  # sha256 → first path seen

    # ----------------------------------------------------------------- scan

    def scan(self, max_images: Optional[int] = None) -> List[dict]:
        """
        Walk images_dir and populate the manifest.
        Returns the list of record dicts.
        """
        self._manifest = []
        self._hash_index = {}

        if not self.images_dir.exists():
            return self._manifest

        image_files = sorted(
            p for p in self.images_dir.rglob("*")
            if p.suffix.lower() in SUPPORTED_EXTS
        )
        if max_images is not None:
            image_files = image_files[:max_images]

        for path in image_files:
            record = self._inspect(path)
            self._manifest.append(record)

        return self._manifest

    def _inspect(self, path: Path) -> dict:
        now = datetime.utcnow().isoformat() + "Z"
        size_bytes = path.stat().st_size if path.exists() else 0

        # --- Hash ---
        try:
            raw = path.read_bytes()
            sha256 = hashlib.sha256(raw).hexdigest()
        except OSError:
            sha256 = None

        # --- Corrupt / dimensions ---
        width = height = None
        is_corrupt = False
        try:
            from PIL import Image
            with Image.open(path) as img:
                img.verify()   # closes after verify
            with Image.open(path) as img:
                width, height = img.size
        except Exception:
            is_corrupt = True

        # --- Duplicate detection via sha256 ---
        is_duplicate = False
        duplicate_of = None
        if sha256:
            if sha256 in self._hash_index:
                is_duplicate = True
                duplicate_of = self._hash_index[sha256]
            else:
                self._hash_index[sha256] = str(path)

        return {
            "path": str(path),
            "filename": path.name,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "width": width,
            "height": height,
            "is_corrupt": is_corrupt,
            "is_duplicate": is_duplicate,
            "duplicate_of": duplicate_of,
            "scanned_at": now,
        }

    # ----------------------------------------------------------------- report

    def build_report(self, output_path: str) -> dict:
        """
        Write the manifest to a CSV at output_path and return summary stats.
        Scans if not already scanned.
        """
        if not self._manifest:
            self.scan()

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            writer.writeheader()
            writer.writerows(self._manifest)

        total = len(self._manifest)
        corrupt = sum(1 for r in self._manifest if r["is_corrupt"])
        dupes = sum(1 for r in self._manifest if r["is_duplicate"])
        valid = total - corrupt - dupes

        summary = {
            "total": total,
            "valid": valid,
            "corrupt": corrupt,
            "duplicates": dupes,
            "output_path": output_path,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }
        return summary

    # ----------------------------------------------------------------- filters

    def get_valid(self) -> List[dict]:
        return [r for r in self._manifest if not r["is_corrupt"] and not r["is_duplicate"]]

    def get_corrupt(self) -> List[str]:
        return [r["path"] for r in self._manifest if r["is_corrupt"]]

    def get_duplicates(self) -> List[Tuple[str, List[str]]]:
        """
        Returns [(canonical_path, [duplicate_paths, ...]), ...].
        """
        groups: Dict[str, List[str]] = {}
        for r in self._manifest:
            if r["is_duplicate"] and r["duplicate_of"]:
                groups.setdefault(r["duplicate_of"], []).append(r["path"])
        return list(groups.items())

    def manifest(self) -> List[dict]:
        return list(self._manifest)

    # ----------------------------------------------------------------- db sync

    def sync_to_db(self, db_path: Optional[str] = None) -> int:
        """
        Upsert valid manifest records into the screenshots table of a
        FlightDatabase-compatible SQLite DB. Returns the number of rows upserted.
        Skips corrupt and duplicate images.
        """
        target = db_path or self.db_path
        if not target:
            raise ValueError("db_path required for sync_to_db")

        valid = self.get_valid()
        if not valid:
            return 0

        conn = sqlite3.connect(target)
        _ensure_schema(conn)
        now = datetime.utcnow().isoformat()
        upserted = 0

        for rec in valid:
            sha256 = rec.get("sha256")
            if not sha256:
                continue
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO screenshots
                       (screenshot_id, image_path, processed_at,
                        sha256, coordinate_method, coordinate_confidence,
                        estimated_error_m, review_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (sha256, rec["path"], now,
                     sha256, "fixed_pr_bounds", 0.65, 1500.0, "pending"),
                )
                upserted += conn.execute(
                    "SELECT changes()"
                ).fetchone()[0]
            except Exception:
                pass

        conn.commit()
        conn.close()
        return upserted


def _ensure_schema(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS screenshots (
            screenshot_id TEXT PRIMARY KEY,
            image_path TEXT,
            flight_id TEXT,
            processed_at TEXT,
            callsign TEXT,
            altitude_ft INTEGER,
            ground_speed_mph INTEGER,
            latitude REAL,
            longitude REAL,
            timestamp TEXT,
            raw_text TEXT,
            ocr_confidence REAL,
            sha256 TEXT,
            coordinate_method TEXT,
            coordinate_confidence REAL,
            estimated_error_m REAL,
            review_status TEXT DEFAULT 'pending'
        )
    """)
    conn.commit()


def scan_directory(images_dir: str,
                   output_csv: Optional[str] = None,
                   max_images: Optional[int] = None,
                   db_path: Optional[str] = None) -> dict:
    """
    Convenience wrapper: scan a directory, optionally write CSV and sync to DB.
    Returns summary stats dict.
    """
    inv = ScreenshotInventory(images_dir, db_path=db_path)
    inv.scan(max_images=max_images)

    summary = {}
    if output_csv:
        summary = inv.build_report(output_csv)
    else:
        total = len(inv.manifest())
        summary = {
            "total": total,
            "valid": len(inv.get_valid()),
            "corrupt": len(inv.get_corrupt()),
            "duplicates": len(inv.get_duplicates()),
        }

    if db_path:
        summary["db_upserted"] = inv.sync_to_db(db_path)

    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FR24 Screenshot Inventory")
    parser.add_argument("images_dir", help="Directory of FR24 screenshots")
    parser.add_argument("--output", "-o", default="screenshot_inventory.csv")
    parser.add_argument("--max", type=int, default=None)
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    result = scan_directory(args.images_dir, args.output, args.max, args.db)
    for k, v in result.items():
        print(f"  {k:<20} {v}")
