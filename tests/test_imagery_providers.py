"""
Tests for imagery providers (mocked HTTP; no network).

Providers' ``_request`` is monkeypatched with a fake dispatcher so we exercise
URL/param construction and response parsing without live services. A single
``@pytest.mark.integration`` test hits the real (auth-free) GIBS endpoint and is
excluded from the default ``-m 'not integration'`` run.
"""

import io
import json
from pathlib import Path

import pytest

from imagery import geo
from imagery.providers import get_provider
from imagery.providers.base import ProviderError, parse_date_range
from imagery.providers.gibs import GibsProvider
from imagery.providers.sentinelhub import SentinelHubProvider

FIXTURES = Path(__file__).parent / "fixtures"


def _png_bytes(color=(10, 20, 30), size=(8, 8)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class FakeResponse:
    def __init__(self, status=200, content=b"", headers=None, payload=None, text=""):
        self.status_code = status
        self.content = content
        self.headers = headers or {}
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json payload")
        return self._payload


# ── date parsing ──────────────────────────────────────────────────────────────
def test_parse_date_range_pair():
    assert parse_date_range("2024-01-01/2024-01-31") == ("2024-01-01", "2024-01-31")


def test_parse_date_range_single():
    assert parse_date_range("2024-01-01") == ("2024-01-01", "2024-01-01")


def test_parse_date_range_empty_raises():
    with pytest.raises(ProviderError):
        parse_date_range("")


# ── GIBS ──────────────────────────────────────────────────────────────────────
def test_gibs_fetch_builds_wms_getmap(monkeypatch):
    prov = GibsProvider()
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return FakeResponse(
            status=200, content=_png_bytes(), headers={"Content-Type": "image/jpeg"}
        )

    monkeypatch.setattr(prov, "_request", fake_request)
    bbox = geo.bbox_from_point(18.2, -66.4, 0.05)
    result = prov.fetch(bbox, "2024-01-01/2024-01-03")

    assert captured["method"] == "GET"
    p = captured["params"]
    assert p["REQUEST"] == "GetMap"
    assert p["LAYERS"] == "MODIS_Terra_CorrectedReflectance_TrueColor"
    # WMS 1.3.0 EPSG:4326 axis order is south,west,north,east.
    assert p["BBOX"] == f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}"
    assert p["TIME"] == "2024-01-03"  # range end (most recent) day
    assert result.provider == "gibs"
    assert result.media_type == "image/jpeg"
    assert result.cloud_cover_pct is None
    assert result.cache_path and Path(result.cache_path).exists()


def test_gibs_fetch_rejects_non_image(monkeypatch):
    prov = GibsProvider()
    monkeypatch.setattr(
        prov,
        "_request",
        lambda *a, **k: FakeResponse(
            status=200, content=b"<xml>error</xml>", headers={"Content-Type": "text/xml"}
        ),
    )
    with pytest.raises(ProviderError):
        prov.fetch([-66.45, 18.15, -66.35, 18.25], "2024-01-01")


def test_gibs_search_returns_daily_descriptors():
    prov = GibsProvider()
    scenes = prov.search([-66.45, 18.15, -66.35, 18.25], "2024-01-01/2024-01-03")
    assert [s.datetime for s in scenes] == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert all(s.cloud_cover_pct is None for s in scenes)


# ── Sentinel Hub (OAuth2 + Catalog + Process) ─────────────────────────────────
def _sh_dispatcher(catalog_payload, image=b""):
    """Return a fake _request that routes token/catalog/process by URL."""

    def fake_request(method, url, **kwargs):
        if "oauth/token" in url or "openid-connect/token" in url:
            return FakeResponse(
                status=200, payload={"access_token": "TOKEN", "expires_in": 3600}
            )
        if "/catalog/" in url:
            return FakeResponse(status=200, payload=catalog_payload)
        if "/process" in url:
            return FakeResponse(
                status=200, content=image, headers={"Content-Type": "image/png"}
            )
        raise AssertionError(f"unexpected url {url}")

    return fake_request


def test_sentinelhub_search_parses_cloud_cover(monkeypatch):
    payload = json.loads((FIXTURES / "imagery_sh_catalog.json").read_text())
    prov = SentinelHubProvider()
    prov.client_id = "id"
    prov.client_secret = "secret"
    monkeypatch.setattr(prov, "_request", _sh_dispatcher(payload))

    scenes = prov.search([-66.45, 18.15, -66.35, 18.25], "2024-01-01/2024-01-31")
    assert len(scenes) == 3
    cover = {s.scene_id: s.cloud_cover_pct for s in scenes}
    assert cover["S2B_MSIL2A_20240120T150000_PR_0"] == 3.1
    assert all(s.provider == "sentinelhub" for s in scenes)


def test_sentinelhub_fetch_uses_least_cloudy_scene(monkeypatch):
    payload = json.loads((FIXTURES / "imagery_sh_catalog.json").read_text())
    prov = SentinelHubProvider()
    prov.client_id = "id"
    prov.client_secret = "secret"
    monkeypatch.setattr(prov, "_request", _sh_dispatcher(payload, image=_png_bytes()))

    result = prov.fetch([-66.45, 18.15, -66.35, 18.25], "2024-01-01/2024-01-31")
    assert result.provider == "sentinelhub"
    assert result.media_type == "image/png"
    # Least-cloudy fixture scene is 3.1% on 2024-01-20.
    assert result.cloud_cover_pct == 3.1
    assert result.acquired_at == "2024-01-20T15:00:00Z"
    assert result.resolution_m == 10.0


def test_sentinelhub_requires_credentials():
    prov = SentinelHubProvider()
    prov.client_id = ""
    prov.client_secret = ""
    with pytest.raises(ProviderError):
        prov.search([-66.45, 18.15, -66.35, 18.25], "2024-01-01/2024-01-31")


# ── registry ──────────────────────────────────────────────────────────────────
def test_registry_resolves_all_providers():
    assert get_provider("gibs").name == "gibs"
    assert get_provider("sentinelhub").name == "sentinelhub"
    assert get_provider("copernicus").name == "copernicus"


def test_registry_unknown_raises():
    with pytest.raises(ProviderError):
        get_provider("nope")


def test_copernicus_uses_cdse_hosts():
    prov = get_provider("copernicus")
    assert "dataspace.copernicus.eu" in prov.base_url
    assert "dataspace.copernicus.eu" in prov.token_url


# ── live (excluded from default runs) ─────────────────────────────────────────
@pytest.mark.integration
def test_gibs_live_fetch():
    prov = GibsProvider()
    result = prov.fetch(geo.bbox_from_point(18.2, -66.4, 0.05), "2023-06-01")
    assert result.image_bytes[:3] in (b"\xff\xd8\xff", b"\x89PN")
