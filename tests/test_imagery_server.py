"""
Tests for the imagery MCP server tool layer.

Exercises the tool implementation functions with mocked providers (no network)
and checks tool registration when FastMCP is installed.
"""

import io

import pytest

from imagery import server
from imagery.models import ImageryResult


def _png_bytes(color=(10, 20, 30)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


class FakeProvider:
    name = "fake"

    def __init__(self, cloud=5.0):
        self._cloud = cloud

    def fetch_point(self, lat, lon, date_range, *, buffer_deg=None, image_size=None):
        # Vary color by date so compare_imagery sees a difference.
        color = (10, 20, 30) if "01-01" in date_range else (200, 180, 160)
        return ImageryResult(
            provider=self.name,
            image_bytes=_png_bytes(color),
            media_type="image/png",
            bbox=[lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05],
            acquired_at=date_range,
            collection="sentinel-2-l2a",
            cloud_cover_pct=self._cloud,
            cache_path=None,
        )

    def search(self, bbox, date_range, *, max_items=10):
        from imagery.models import SceneMetadata

        return [
            SceneMetadata(
                provider=self.name,
                scene_id="SCENE-1",
                datetime="2024-01-15T15:00:00Z",
                collection="sentinel-2-l2a",
                cloud_cover_pct=self._cloud,
                bbox=bbox,
            )
        ]


def test_list_tool_names():
    assert server.list_tool_names() == [
        "fetch_imagery",
        "query_imagery_metadata",
        "compare_imagery",
    ]


def test_fetch_imagery_tool(monkeypatch):
    monkeypatch.setattr(server, "get_provider", lambda name: FakeProvider())
    out = server.fetch_imagery(
        18.2, -66.4, "2024-01-01", provider="fake", persist=False
    )
    assert out["ok"] is True
    assert out["provider"] == "fake"
    assert out["cloud_cover_pct"] == 5.0
    assert "image_base64" in out
    assert "persisted" not in out  # persist=False


def test_fetch_imagery_persist_invokes_sink(monkeypatch):
    monkeypatch.setattr(server, "get_provider", lambda name: FakeProvider())
    captured = {}

    def fake_persist(result, synthetic=False):
        captured["result"] = result
        return {"persisted": True, "status": "accepted"}

    monkeypatch.setattr(server.sink, "persist", fake_persist)
    out = server.fetch_imagery(18.2, -66.4, "2024-01-01", provider="fake")
    assert out["persisted"]["status"] == "accepted"
    assert captured["result"].provider == "fake"


def test_fetch_imagery_omit_image(monkeypatch):
    monkeypatch.setattr(server, "get_provider", lambda name: FakeProvider())
    out = server.fetch_imagery(
        18.2, -66.4, "2024-01-01", provider="fake", persist=False, include_image=False
    )
    assert "image_base64" not in out
    assert out["size_bytes"] > 0


def test_query_imagery_metadata_tool(monkeypatch):
    monkeypatch.setattr(server, "get_provider", lambda name: FakeProvider())
    out = server.query_imagery_metadata(
        [-66.45, 18.15, -66.35, 18.25], "2024-01-01/2024-01-31", provider="fake"
    )
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["scenes"][0]["scene_id"] == "SCENE-1"


def test_compare_imagery_tool(monkeypatch):
    monkeypatch.setattr(server, "get_provider", lambda name: FakeProvider())
    out = server.compare_imagery(
        18.2, -66.4, "2024-01-01", "2024-02-01", provider="fake"
    )
    assert out["ok"] is True
    assert 0.0 <= out["changed_fraction"] <= 1.0
    # Different colors on the two dates → some change detected.
    assert out["changed_pct"] > 0.0
    assert "image1" not in out or "image_base64" not in out["image1"]


def test_tool_error_surfaces_as_dict(monkeypatch):
    from imagery.providers.base import ProviderError

    def boom(name):
        raise ProviderError("bad provider")

    monkeypatch.setattr(server, "get_provider", boom)
    out = server.fetch_imagery(18.2, -66.4, "2024-01-01", provider="x", persist=False)
    assert out["ok"] is False
    assert "bad provider" in out["error"]


def test_build_server_registers_three_tools():
    pytest.importorskip("fastmcp")
    import asyncio

    mcp = server.build_server()
    tools = asyncio.run(mcp.get_tools())
    names = set(tools.keys()) if isinstance(tools, dict) else {t.name for t in tools}
    assert {"fetch_imagery", "query_imagery_metadata", "compare_imagery"} <= names
