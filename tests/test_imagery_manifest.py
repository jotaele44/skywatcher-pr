"""
Tests for imagery.manifest and the skywatcher persistence sink.

skywatcher-pr has no SatelliteIngest pipeline, so the manifest is validated
directly against the ported satellite_source_manifest schema (the same contract
spiderweb-pr enforces) via the imagery.sink validator.
"""

import io

from imagery import sink
from imagery.manifest import build_manifest
from imagery.models import ImageryResult


def _png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (12, 34, 56)).save(buf, format="PNG")
    return buf.getvalue()


def _result(cloud=3.1, cache_path=None) -> ImageryResult:
    return ImageryResult(
        provider="sentinelhub",
        image_bytes=_png_bytes(),
        media_type="image/png",
        bbox=[-66.45, 18.15, -66.35, 18.25],
        acquired_at="2024-01-20T15:00:00Z",
        collection="sentinel-2-l2a",
        platform="Sentinel-2",
        instrument="MSI",
        cloud_cover_pct=cloud,
        resolution_m=10.0,
        scene_id="S2B_TEST",
        cache_path=cache_path,
    )


def test_manifest_has_required_shape():
    doc = build_manifest(_result(), synthetic=True)
    for key in (
        "manifest_id", "schema_version", "producer", "created_at", "synthetic",
        "source", "acquisition", "asset", "geometry", "puerto_rico", "quality", "lineage",
    ):
        assert key in doc
    assert len(doc["asset"]["checksum_sha256"]) == 64
    assert doc["geometry"]["crs"] == "EPSG:4326"
    assert doc["quality"]["cloud_cover_pct"] == 3.1


def test_manifest_cloud_none_is_unverified():
    doc = build_manifest(_result(cloud=None), synthetic=True)
    assert doc["quality"]["cloud_cover_pct"] == 0.0
    assert doc["quality"]["source_reliability"] == "unverified"


def test_manifest_validates_against_schema():
    doc = build_manifest(_result(), synthetic=True)
    assert sink._validate(doc) == []


def test_persist_writes_accepted_manifest(tmp_path, monkeypatch):
    # Redirect the manifests dir into the tmp path so tests don't touch data/.
    monkeypatch.setattr(sink, "_MANIFESTS_DIR", tmp_path / "satellite_manifests")
    out = sink.persist(_result(), synthetic=True)
    assert out["persisted"] is True
    assert out["status"] == "accepted"
    from pathlib import Path

    assert Path(out["output_path"]).exists()


def test_manifest_bbox_clamped_into_pr_envelope():
    r = _result()
    r.bbox = [-70.0, 10.0, -60.0, 30.0]
    doc = build_manifest(r, synthetic=True)
    west, south, east, north = doc["geometry"]["bbox"]
    assert -68.2 <= west <= -65.1
    assert 17.8 <= south <= 18.7
    assert -68.2 <= east <= -65.1
    assert 17.8 <= north <= 18.7
