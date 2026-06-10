"""Tests for FR24EventExporter and ManualReviewQueue adapter compatibility."""

import csv
import sqlite3
from pathlib import Path

import pytest

from fr24.event_export import FR24EventExporter
from fr24.manual_review_queue import ManualReviewQueue, QUEUE_TYPES
from fr24.screenshot_inventory import ScreenshotInventory


# ------------------------------------------------------------------ review queue

def test_manual_review_queue_init(tmp_path):
    q = ManualReviewQueue(str(tmp_path))
    assert (tmp_path / "review_queue.db").exists()


def test_manual_review_add_and_get(tmp_path):
    q = ManualReviewQueue(str(tmp_path))
    item_id = q.add_item("route_georef", "/tmp/img.jpg", "Missing route")
    assert len(item_id) == 36  # UUID format

    pending = q.get_pending("route_georef")
    assert len(pending) == 1
    assert pending[0]["image_path"] == "/tmp/img.jpg"
    assert pending[0]["status"] == "pending"


def test_manual_review_idempotent_add(tmp_path):
    q = ManualReviewQueue(str(tmp_path))
    id1 = q.add_item("ocr_correction", "/tmp/img.jpg", "Bad OCR")
    id2 = q.add_item("ocr_correction", "/tmp/img.jpg", "Bad OCR again")
    assert id1 == id2  # same pending item returned
    assert len(q.get_pending("ocr_correction")) == 1


def test_manual_review_mark_reviewed(tmp_path):
    q = ManualReviewQueue(str(tmp_path))
    item_id = q.add_item("quality_issue", "/tmp/small.jpg", "Too small")
    success = q.mark_reviewed(item_id, "accepted", "OK for testing")
    assert success
    pending = q.get_pending("quality_issue")
    assert len(pending) == 0


def test_manual_review_invalid_queue_type(tmp_path):
    q = ManualReviewQueue(str(tmp_path))
    with pytest.raises(ValueError):
        q.add_item("invalid_type", "/tmp/img.jpg", "reason")


def test_manual_review_all_queue_types(tmp_path):
    q = ManualReviewQueue(str(tmp_path))
    for qt in QUEUE_TYPES:
        item_id = q.add_item(qt, f"/tmp/{qt}_img.jpg", f"Test {qt}")
        assert item_id is not None


def test_manual_review_export_csv(tmp_path):
    q = ManualReviewQueue(str(tmp_path))
    q.add_item("route_georef", "/tmp/img1.jpg", "reason 1")
    q.add_item("ocr_correction", "/tmp/img2.jpg", "reason 2")
    out = q.export_csv()
    assert Path(out).exists()
    with open(out, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2


def test_manual_review_export_csv_filtered(tmp_path):
    q = ManualReviewQueue(str(tmp_path))
    q.add_item("route_georef", "/tmp/img1.jpg", "r1")
    q.add_item("ocr_correction", "/tmp/img2.jpg", "r2")
    out = q.export_csv(queue_type="route_georef")
    with open(out, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["queue_type"] == "route_georef"


def test_manual_review_stats(tmp_path):
    q = ManualReviewQueue(str(tmp_path))
    q.add_item("route_georef", "/tmp/a.jpg", "r1")
    q.add_item("route_georef", "/tmp/b.jpg", "r2")
    item_id = q.add_item("ocr_correction", "/tmp/c.jpg", "r3")
    q.mark_reviewed(item_id, "fixed")
    stats = q.get_stats()
    assert stats["_total"] == 3
    assert stats["route_georef"]["pending"] == 2


def test_mark_flagged(tmp_path):
    q = ManualReviewQueue(str(tmp_path))
    item_id = q.add_item("quality_issue", "/tmp/img.jpg", "bad")
    q.mark_flagged(item_id, "needs re-scan")
    all_items = q.get_all(status="flagged")
    assert len(all_items) == 1


# ------------------------------------------------------------------ exporter

def test_fr24_event_exporter_init(populated_db, tmp_path):
    exp = FR24EventExporter(populated_db, review_dir=str(tmp_path / "review"))
    assert exp is not None


def test_export_inventory_inserts_records(populated_db, tmp_path):
    manifest = [
        {
            "path": f"/tmp/img_{i}.jpg",
            "filename": f"img_{i}.jpg",
            "size_bytes": 1024,
            "sha256": "a" * 63 + str(i),
            "width": 1024,
            "height": 768,
            "is_corrupt": False,
            "is_duplicate": False,
            "duplicate_of": None,
            "scanned_at": "2024-03-15T08:00:00Z",
        }
        for i in range(3)
    ]
    exp = FR24EventExporter(populated_db, review_dir=str(tmp_path / "review"))
    inserted = exp.export_inventory_to_db(manifest)
    assert inserted == 3


def test_export_inventory_skips_corrupt(populated_db, tmp_path):
    manifest = [
        {
            "path": "/tmp/corrupt.jpg",
            "filename": "corrupt.jpg",
            "size_bytes": 100,
            "sha256": "b" * 64,
            "width": None,
            "height": None,
            "is_corrupt": True,
            "is_duplicate": False,
            "duplicate_of": None,
            "scanned_at": "2024-03-15T08:00:00Z",
        }
    ]
    exp = FR24EventExporter(populated_db, review_dir=str(tmp_path / "review"))
    inserted = exp.export_inventory_to_db(manifest)
    assert inserted == 0


def test_export_inventory_idempotent(populated_db, tmp_path):
    manifest = [
        {
            "path": "/tmp/img_idem.jpg",
            "filename": "img_idem.jpg",
            "size_bytes": 512,
            "sha256": "c" * 64,
            "width": 800,
            "height": 600,
            "is_corrupt": False,
            "is_duplicate": False,
            "duplicate_of": None,
            "scanned_at": "2024-03-15T08:00:00Z",
        }
    ]
    exp = FR24EventExporter(populated_db, review_dir=str(tmp_path / "review"))
    first = exp.export_inventory_to_db(manifest)
    second = exp.export_inventory_to_db(manifest)
    assert first == 1
    assert second == 0  # already inserted


def test_export_batch_empty_dir(populated_db, tmp_path):
    empty = tmp_path / "empty_imgs"
    empty.mkdir()
    exp = FR24EventExporter(populated_db, review_dir=str(tmp_path / "review"))
    report = exp.export_batch(str(empty))
    assert report["total_scanned"] == 0
    assert report["screenshots_upserted"] == 0


def test_adapter_schema_compatibility(populated_db):
    """Exported records must be compatible with the screenshots table schema."""
    conn = sqlite3.connect(populated_db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(screenshots)").fetchall()}
    conn.close()

    required_cols = {
        "screenshot_id", "image_path", "processed_at",
        "sha256", "coordinate_method", "coordinate_confidence",
        "estimated_error_m", "review_status",
    }
    missing = required_cols - cols
    assert not missing, f"Schema missing cols: {missing}"


def test_export_route_events_returns_zero_on_empty(populated_db, tmp_path):
    exp = FR24EventExporter(populated_db, review_dir=str(tmp_path / "review"))
    inserted = exp.export_route_events("/tmp/no_img.jpg", routes=[])
    assert inserted == 0


def test_get_export_report_has_expected_keys(populated_db, tmp_path):
    exp = FR24EventExporter(populated_db, review_dir=str(tmp_path / "review"))
    report = exp.get_export_report()
    expected = {"generated_at", "db_path", "screenshots_upserted",
                "track_points_inserted", "review_items_added", "errors"}
    assert expected.issubset(set(report.keys()))


def test_export_route_events_malformed_path_returns_zero(populated_db, tmp_path):
    from fr24.event_export import FR24EventExporter
    exp = FR24EventExporter(populated_db, review_dir=str(tmp_path / "review"))
    inserted = exp.export_route_events("/nonexistent/malformed.jpg", routes=[])
    assert inserted == 0
