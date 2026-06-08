"""
MANUAL REVIEW QUEUE
SQLite-backed queue for route georeferencing, OCR corrections, coordinate
calibration issues, and screenshot quality problems.
"""

import csv
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


QUEUE_TYPES = ("route_georef", "ocr_correction", "quality_issue", "coord_calibration")

SCHEMA = """
CREATE TABLE IF NOT EXISTS review_queue (
    item_id     TEXT PRIMARY KEY,
    queue_type  TEXT NOT NULL,
    image_path  TEXT NOT NULL,
    reason      TEXT NOT NULL,
    metadata    TEXT,
    status      TEXT DEFAULT 'pending',
    resolution  TEXT,
    reviewer_notes TEXT,
    created_at  TEXT NOT NULL,
    reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_rq_queue ON review_queue(queue_type, status);
CREATE INDEX IF NOT EXISTS idx_rq_path  ON review_queue(image_path);
"""

EXPORT_FIELDNAMES = [
    "item_id", "queue_type", "image_path", "reason",
    "metadata", "status", "resolution", "reviewer_notes",
    "created_at", "reviewed_at",
]


class ManualReviewQueue:
    """
    Manages review queues for FR24 screenshot processing.

    All state is persisted in a SQLite DB at <output_dir>/review_queue.db
    so that items survive process restarts and can be shared across tools.
    """

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.output_dir / "review_queue.db")
        self._init_schema()

    # ----------------------------------------------------------------- add

    def add_item(self,
                 queue_type: str,
                 image_path: str,
                 reason: str,
                 metadata: Optional[Dict] = None) -> str:
        """
        Add a new item to the queue. Returns the assigned item_id.
        Duplicate (image_path, queue_type) entries for items still pending
        are silently skipped (idempotent on re-scan).
        """
        if queue_type not in QUEUE_TYPES:
            raise ValueError(f"queue_type must be one of {QUEUE_TYPES}")

        import json as _json
        conn = self._connect()
        # Check for existing pending item with same path + type
        row = conn.execute(
            "SELECT item_id FROM review_queue "
            "WHERE queue_type=? AND image_path=? AND status='pending'",
            (queue_type, image_path),
        ).fetchone()
        if row:
            conn.close()
            return row[0]

        item_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO review_queue "
            "(item_id, queue_type, image_path, reason, metadata, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (item_id, queue_type, image_path, reason,
             _json.dumps(metadata) if metadata else None,
             datetime.utcnow().isoformat() + "Z"),
        )
        conn.commit()
        conn.close()
        return item_id

    # ----------------------------------------------------------------- query

    def get_pending(self, queue_type: Optional[str] = None) -> List[dict]:
        conn = self._connect()
        if queue_type:
            rows = conn.execute(
                "SELECT * FROM review_queue WHERE queue_type=? AND status='pending' "
                "ORDER BY created_at",
                (queue_type,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM review_queue WHERE status='pending' ORDER BY created_at"
            ).fetchall()
        conn.close()
        return [_row_to_dict(r) for r in rows]

    def get_all(self, queue_type: Optional[str] = None,
                status: Optional[str] = None) -> List[dict]:
        conn = self._connect()
        clauses = []
        params = []
        if queue_type:
            clauses.append("queue_type=?")
            params.append(queue_type)
        if status:
            clauses.append("status=?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM review_queue {where} ORDER BY created_at",
            params,
        ).fetchall()
        conn.close()
        return [_row_to_dict(r) for r in rows]

    # ----------------------------------------------------------------- update

    def mark_reviewed(self, item_id: str,
                      resolution: str,
                      reviewer_notes: str = "") -> bool:
        conn = self._connect()
        affected = conn.execute(
            "UPDATE review_queue SET status='reviewed', resolution=?, "
            "reviewer_notes=?, reviewed_at=? WHERE item_id=?",
            (resolution, reviewer_notes,
             datetime.utcnow().isoformat() + "Z", item_id),
        ).rowcount
        conn.commit()
        conn.close()
        return affected > 0

    def mark_flagged(self, item_id: str, reason: str = "") -> bool:
        conn = self._connect()
        affected = conn.execute(
            "UPDATE review_queue SET status='flagged', reviewer_notes=? "
            "WHERE item_id=?",
            (reason, item_id),
        ).rowcount
        conn.commit()
        conn.close()
        return affected > 0

    # ----------------------------------------------------------------- export

    def export_csv(self,
                   queue_type: Optional[str] = None,
                   output_path: Optional[str] = None) -> str:
        items = self.get_all(queue_type=queue_type)
        if output_path is None:
            suffix = f"_{queue_type}" if queue_type else ""
            output_path = str(self.output_dir / f"review_queue{suffix}.csv")

        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=EXPORT_FIELDNAMES,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(items)
        return output_path

    def get_pending_count(self, queue_type: Optional[str] = None) -> int:
        """Return the number of pending items (optionally filtered by type)."""
        conn = self._connect()
        if queue_type:
            row = conn.execute(
                "SELECT COUNT(*) FROM review_queue WHERE queue_type=? AND status='pending'",
                (queue_type,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM review_queue WHERE status='pending'"
            ).fetchone()
        conn.close()
        return row[0] if row else 0

    def bulk_approve(self, item_ids: List[str], resolution: str = "bulk_approved") -> int:
        """Mark multiple items as reviewed in one transaction.

        Returns the number of items actually updated (skips unknown IDs).
        """
        if not item_ids:
            return 0
        now = datetime.utcnow().isoformat() + "Z"
        conn = self._connect()
        affected = 0
        for item_id in item_ids:
            affected += conn.execute(
                "UPDATE review_queue SET status='reviewed', resolution=?, reviewed_at=? "
                "WHERE item_id=?",
                (resolution, now, item_id),
            ).rowcount
        conn.commit()
        conn.close()
        return affected

    def export_to_json(self, output_path: Optional[str] = None,
                       queue_type: Optional[str] = None) -> str:
        """Export all items (optionally filtered by type) to a JSON file.

        Returns the path of the written file.
        """
        import json as _json
        items = self.get_all(queue_type=queue_type)
        if output_path is None:
            suffix = f"_{queue_type}" if queue_type else ""
            output_path = str(self.output_dir / f"review_queue{suffix}.json")
        with open(output_path, "w", encoding="utf-8") as f:
            _json.dump(
                {"exported_at": datetime.utcnow().isoformat() + "Z", "items": items},
                f,
                indent=2,
            )
        return output_path

    # ----------------------------------------------------------------- stats

    def get_stats(self) -> Dict:
        conn = self._connect()
        rows = conn.execute(
            "SELECT queue_type, status, COUNT(*) FROM review_queue "
            "GROUP BY queue_type, status"
        ).fetchall()
        conn.close()

        stats: Dict = {}
        for qtype, status, count in rows:
            stats.setdefault(qtype, {})[status] = count

        total = sum(
            v for row in stats.values() for v in row.values()
        )
        stats["_total"] = total
        return stats

    # ----------------------------------------------------------------- internal

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        conn = self._connect()
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)
