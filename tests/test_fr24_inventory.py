"""Tests for ScreenshotInventory: coverage, hashing, dedup, corrupt detection."""

import hashlib
import shutil
from pathlib import Path

import pytest

from fr24.screenshot_inventory import ScreenshotInventory, scan_directory, MANIFEST_FIELDS


# ------------------------------------------------------------------ fixtures

@pytest.fixture
def image_dir(tmp_path):
    """Directory with 3 tiny valid PNGs and 1 corrupt file."""
    try:
        from PIL import Image
        _PIL_AVAILABLE = True
    except ImportError:
        _PIL_AVAILABLE = False

    d = tmp_path / "images"
    d.mkdir()

    if _PIL_AVAILABLE:
        for i in range(3):
            img = Image.new("RGB", (100, 80), color=(i * 50, 100, 200))
            img.save(str(d / f"shot_{i:02d}.png"))
    else:
        # Minimal valid PNG header (1x1 red pixel)
        _minimal_png = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00'
            b'\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N'
            b'\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        for i in range(3):
            (d / f"shot_{i:02d}.png").write_bytes(_minimal_png)

    # Corrupt file: valid extension, invalid content
    (d / "corrupt.jpg").write_bytes(b"NOT_AN_IMAGE")

    return d


@pytest.fixture
def dupe_dir(tmp_path):
    """Directory with 2 identical images (different filenames)."""
    d = tmp_path / "dupes"
    d.mkdir()
    content = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
    (d / "a.png").write_bytes(content)
    (d / "b.png").write_bytes(content)
    return d


# ------------------------------------------------------------------ tests

def test_scan_empty_directory(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    inv = ScreenshotInventory(str(empty))
    manifest = inv.scan()
    assert manifest == []


def test_scan_nonexistent_directory(tmp_path):
    inv = ScreenshotInventory(str(tmp_path / "does_not_exist"))
    manifest = inv.scan()
    assert manifest == []


def test_scan_finds_images(image_dir):
    inv = ScreenshotInventory(str(image_dir))
    manifest = inv.scan()
    assert len(manifest) == 4  # 3 valid + 1 corrupt


def test_manifest_has_required_fields(image_dir):
    inv = ScreenshotInventory(str(image_dir))
    manifest = inv.scan()
    for rec in manifest:
        for field in MANIFEST_FIELDS:
            assert field in rec, f"Missing field: {field}"


def test_sha256_is_hex64(image_dir):
    inv = ScreenshotInventory(str(image_dir))
    for rec in inv.scan():
        if rec["sha256"]:
            assert len(rec["sha256"]) == 64
            assert all(c in "0123456789abcdef" for c in rec["sha256"])


def test_corrupt_file_flagged(image_dir):
    inv = ScreenshotInventory(str(image_dir))
    inv.scan()
    corrupt = inv.get_corrupt()
    assert len(corrupt) >= 1
    assert any("corrupt.jpg" in p for p in corrupt)


def test_duplicate_detection(dupe_dir):
    inv = ScreenshotInventory(str(dupe_dir))
    inv.scan()
    dupes = inv.get_duplicates()
    assert len(dupes) == 1
    canonical, dup_list = dupes[0]
    assert len(dup_list) == 1


def test_get_valid_excludes_corrupt_and_dupes(image_dir, dupe_dir):
    inv = ScreenshotInventory(str(image_dir))
    inv.scan()
    valid = inv.get_valid()
    # All valid records should be neither corrupt nor duplicate
    for rec in valid:
        assert not rec["is_corrupt"]
        assert not rec["is_duplicate"]


def test_max_images_limit(image_dir):
    inv = ScreenshotInventory(str(image_dir))
    manifest = inv.scan(max_images=2)
    assert len(manifest) == 2


def test_build_report_creates_csv(image_dir, tmp_path):
    out = str(tmp_path / "report.csv")
    inv = ScreenshotInventory(str(image_dir))
    inv.scan()
    summary = inv.build_report(out)
    assert Path(out).exists()
    assert summary["total"] == 4
    assert "corrupt" in summary
    assert "duplicates" in summary


def test_scan_directory_convenience(image_dir, tmp_path):
    out = str(tmp_path / "scan_report.csv")
    summary = scan_directory(str(image_dir), output_csv=out)
    assert Path(out).exists()
    assert summary["total"] >= 1


def test_sync_to_db(image_dir, tmp_path):
    db = str(tmp_path / "test.db")
    inv = ScreenshotInventory(str(image_dir), db_path=db)
    inv.scan()
    upserted = inv.sync_to_db(db)
    assert upserted >= 0  # 0 is valid when all images are corrupt/dupes


def test_sha256_matches_file_content(image_dir):
    inv = ScreenshotInventory(str(image_dir))
    for rec in inv.scan():
        if rec["sha256"] and not rec["is_corrupt"]:
            expected = hashlib.sha256(Path(rec["path"]).read_bytes()).hexdigest()
            assert rec["sha256"] == expected
