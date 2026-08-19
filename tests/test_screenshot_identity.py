"""Gate: SHA-256 screenshot identity (synthetic bytes / tmp files)."""

from __future__ import annotations

import hashlib

import pytest

from skywatcher.fr24 import screenshot_identity as si


def test_sha256_of_bytes_matches_hashlib():
    data = b"synthetic-screenshot-bytes"
    assert si.sha256_of_bytes(data) == hashlib.sha256(data).hexdigest()


def test_screenshot_id_alias_equals_sha256():
    data = b"abc"
    assert si.screenshot_id_for_bytes(data) == si.sha256_of_bytes(data)


def test_sha256_of_file_matches_bytes(tmp_path):
    p = tmp_path / "img.png"
    data = b"\x89PNG\r\n synthetic"
    p.write_bytes(data)
    assert si.sha256_of_file(p) == si.sha256_of_bytes(data)
    assert si.screenshot_id_for_file(p) == hashlib.sha256(data).hexdigest()


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        si.sha256_of_file(tmp_path / "nope.png")


def test_non_bytes_raises():
    with pytest.raises(TypeError):
        si.sha256_of_bytes("not-bytes")  # type: ignore[arg-type]
