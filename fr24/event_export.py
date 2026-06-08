"""
FR24 EVENT EXPORT
Exports screenshot-derived events (inventory records, extracted routes,
OCR data) into the existing FlightDatabase-compatible airspace SQLite schema.
Acts as the bridge between the FR24 screenshot processor and the PR Intel
integration pipeline.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fr24.screenshot_inventory import ScreenshotInventory, _ensure_schema
from fr24.ui_segmenter import FR24UISegmenter
from fr24.route_extractor import RouteExtractor, RouteCandidate
from fr24.manual_review_queue import ManualReviewQueue


class FR24EventExporter:
    """
    Exports screenshot-derived events into the airspace SQLite database.

    Pipeline:
      inventory.scan() → upsert screenshots table
      segment + extract routes → upsert track_points table
      low-quality items → ManualReviewQueue
    """

    # Route-to-track-point confidence thresholds
    MIN_ROUTE_CONFIDENCE = 0.10
    OCR_LOW_CONF_THRESHOLD = 0.40

    def __init__(self,
                 db_path: str,
                 review_dir: Optional[str] = None,
                 segmenter: Optional[FR24UISegmenter] = None,
                 extractor: Optional[RouteExtractor] = None):
        self.db_path = db_path
        self._review_dir = review_dir or str(Path(db_path).parent / "review")
        self._review_queue = ManualReviewQueue(self._review_dir)
        self._segmenter = segmenter or FR24UISegmenter(mode="geometric")
        self._extractor = extractor or RouteExtractor(segmenter=self._segmenter)
        self._stats: Dict[str, int] = {
            "screenshots_upserted": 0,
            "track_points_inserted": 0,
            "review_items_added": 0,
            "errors": 0,
        }

        conn = sqlite3.connect(self.db_path)
        _ensure_schema(conn)
        _ensure_track_points_schema(conn)
        conn.close()

    # ----------------------------------------------------------------- inventory

    def export_inventory_to_db(self, manifest: List[dict]) -> int:
        """
        Upsert screenshot records from an inventory manifest into the
        screenshots table. Returns count of newly inserted rows.
        """
        conn = sqlite3.connect(self.db_path)
        _ensure_schema(conn)
        now = datetime.utcnow().isoformat() + "Z"
        inserted = 0

        for rec in manifest:
            if rec.get("is_corrupt") or rec.get("is_duplicate"):
                continue
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
                    (sha256, rec["path"], now, sha256,
                     "fixed_pr_bounds", 0.65, 1500.0, "pending"),
                )
                inserted += conn.execute("SELECT changes()").fetchone()[0]

                # Route low-quality items to review queue
                if rec.get("width") and rec.get("height"):
                    w, h = rec["width"], rec["height"]
                    if w < 400 or h < 300:
                        self._review_queue.add_item(
                            "quality_issue", rec["path"],
                            f"Image too small: {w}×{h}",
                        )
                        self._stats["review_items_added"] += 1
            except Exception:
                self._stats["errors"] += 1

        conn.commit()
        conn.close()
        self._stats["screenshots_upserted"] += inserted
        return inserted

    # ----------------------------------------------------------------- routes

    def export_route_events(self,
                            image_path: str,
                            routes: List[RouteCandidate],
                            flight_id: Optional[str] = None,
                            screenshot_id: Optional[str] = None) -> int:
        """
        Convert extracted route candidates to track_point rows.
        Only high-confidence routes (>= MIN_ROUTE_CONFIDENCE) are exported.
        Returns number of track_point rows inserted.
        """
        from integration.geo_calibration import GeoCalibration

        if not routes:
            return 0

        # Get image dimensions for coordinate conversion
        try:
            from PIL import Image as _PIL
            with _PIL.open(image_path) as _img:
                img_w, img_h = _img.size
        except Exception:
            img_w, img_h = 1024, 768

        cal = GeoCalibration(mode="fixed_pr_bounds")
        conn = sqlite3.connect(self.db_path)
        _ensure_track_points_schema(conn)
        now = datetime.utcnow().isoformat()
        inserted = 0

        for route in routes:
            if route.confidence < self.MIN_ROUTE_CONFIDENCE:
                continue
            sampled = _sample_points(route.points, max_pts=30)
            for px, py in sampled:
                coord = cal.pixel_to_coord(px, py, img_w, img_h)
                if not coord.in_pr_bbox():
                    continue
                try:
                    conn.execute(
                        """INSERT INTO track_points
                           (flight_id, timestamp, latitude, longitude,
                            altitude_ft, ground_speed_mph)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (flight_id, now, coord.lat, coord.lon, 0, 0),
                    )
                    inserted += conn.execute("SELECT changes()").fetchone()[0]
                except Exception:
                    self._stats["errors"] += 1

        conn.commit()
        conn.close()
        self._stats["track_points_inserted"] += inserted
        return inserted

    # ----------------------------------------------------------------- batch

    def export_batch(self,
                     images_dir: str,
                     max_images: Optional[int] = None) -> Dict[str, Any]:
        """
        Full pipeline over a directory:
          1. inventory.scan()
          2. export inventory to screenshots table
          3. extract routes from each valid image
          4. export route events as track_points
        Returns summary report dict.
        """
        # Reset per-batch stats
        for k in self._stats:
            self._stats[k] = 0

        inv = ScreenshotInventory(images_dir)
        manifest = inv.scan(max_images=max_images)

        self.export_inventory_to_db(manifest)

        route_files_processed = 0
        for rec in inv.get_valid():
            try:
                routes = self._extractor.extract(rec["path"])
                if routes:
                    self.export_route_events(
                        rec["path"], routes,
                        screenshot_id=rec.get("sha256"),
                    )
                route_files_processed += 1
            except Exception:
                self._stats["errors"] += 1

        return self.get_export_report(
            images_dir=images_dir,
            total_scanned=len(manifest),
            valid=len(inv.get_valid()),
            corrupt=len(inv.get_corrupt()),
            duplicates=len(inv.get_duplicates()),
            route_files_processed=route_files_processed,
        )

    # ----------------------------------------------------------------- report

    def get_export_report(self, **extra) -> Dict[str, Any]:
        report = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "db_path": self.db_path,
            **self._stats,
            **extra,
        }
        return report


# ------------------------------------------------------------------ helpers

def _ensure_track_points_schema(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS track_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_id TEXT,
            timestamp TEXT,
            latitude REAL,
            longitude REAL,
            altitude_ft INTEGER,
            ground_speed_mph INTEGER
        )
    """)
    conn.commit()


def _sample_points(pts: List, max_pts: int) -> List:
    """Evenly sample up to max_pts from pts list."""
    if len(pts) <= max_pts:
        return pts
    step = len(pts) / max_pts
    return [pts[int(i * step)] for i in range(max_pts)]
