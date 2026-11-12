"""The curated Sky Cameras catalog obeys its schema and inclusion rules."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from skywatcher.core.cameras import (
    coverage_summary,
    embed_url,
    filter_cameras,
    load_catalog,
    load_municipios,
    parse_embed,
    sniff_video,
    validate_https_url,
)
from skywatcher.core.cameras.validation import SubmissionError

ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = ROOT / "data" / "reference" / "sky_cameras"
RAW = json.loads((CATALOG_DIR / "cameras.v1.json").read_text(encoding="utf-8"))
MUNICIPIOS = load_municipios(ROOT / "data" / "geo" / "pr_municipios_boundaries.json")


def test_catalog_matches_schema():
    schema = json.loads((ROOT / "schemas" / "sky_camera.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(RAW, schema)


def test_ids_unique_and_municipalities_real():
    ids = [row["id"] for row in RAW["cameras"]]
    assert len(ids) == len(set(ids))
    assert len(MUNICIPIOS) == 78
    for row in RAW["cameras"]:
        assert row["municipality"] in MUNICIPIOS, row["id"]


def test_urls_are_https_and_embeds_allowlisted():
    for camera in load_catalog(CATALOG_DIR):
        validate_https_url(camera.page_url)
        validate_https_url(camera.source_url)
        if camera.embed:
            url = embed_url(camera.embed)
            assert url and url.startswith(("https://www.youtube-nocookie.com/", "https://player.vimeo.com/"))


def test_filter_and_coverage():
    cameras = load_catalog(CATALOG_DIR)
    beaches = filter_cameras(cameras, category="beach")
    assert beaches and all("beach" in camera.categories for camera in beaches)
    assert filter_cameras(cameras, municipality="rio grande")  # accent-insensitive
    assert filter_cameras(cameras, q="condado")
    summary = coverage_summary(cameras, MUNICIPIOS)
    assert summary["camera_count"] == len(cameras)
    assert summary["municipio_total"] == 78
    assert summary["municipios_covered"] + len(summary["municipios_without_cameras"]) == 78
    # Gaps are reported, not hidden.
    assert "river" in summary["categories_without_cameras"]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/watch?v=taI7GiyvDxE", {"kind": "youtube", "video_id": "taI7GiyvDxE"}),
        ("https://youtu.be/taI7GiyvDxE", {"kind": "youtube", "video_id": "taI7GiyvDxE"}),
        ("https://www.youtube.com/live/taI7GiyvDxE?si=x", {"kind": "youtube", "video_id": "taI7GiyvDxE"}),
        ("https://vimeo.com/123456789", {"kind": "vimeo", "video_id": "123456789"}),
        ("https://www.skylinewebcams.com/en/webcam/puerto-rico.html", None),
        ("https://evil.example/watch?v=taI7GiyvDxE", None),
    ],
)
def test_parse_embed(url, expected):
    assert parse_embed(url) == expected


@pytest.mark.parametrize(
    "url",
    ["http://example.com/cam", "javascript:alert(1)", "https://user:pw@example.com/", "https://localhost/x", ""],
)
def test_rejects_unsafe_urls(url):
    with pytest.raises(SubmissionError):
        validate_https_url(url)


def test_sniff_video():
    assert sniff_video(b"\x00\x00\x00\x18ftypisom\x00\x00").extension == "mp4"
    assert sniff_video(b"\x00\x00\x00\x14ftypqt  \x00\x00").extension == "mov"
    assert sniff_video(b"\x1a\x45\xdf\xa3\x01\x00").extension == "webm"
    assert sniff_video(b"<html><script>") is None
