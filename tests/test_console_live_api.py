"""API tests for /api/console/live/* with a fake provider (no network)."""

from datetime import date, datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from adsb.heatmap import decode_heatmap, encode_heatmap  # noqa: E402
from adsb.providers.adsblol import UpstreamNotFound  # noqa: E402
from adsb.providers.base import ProviderError  # noqa: E402
from server.backend.console import live_router  # noqa: E402
from server.backend.main import app  # noqa: E402

LATEST = datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)


class FakeProvider:
    site_base = "https://site.test"
    api_base = "https://api.test"

    def __init__(self, fail=False, error=None):
        self.fail = fail
        self.error = error or ProviderError("upstream down at https://internal.example/secret-path")
        self.calls = []

    def _maybe_fail(self):
        if self.fail:
            raise self.error

    def fetch_aircraft(self, bbox, military=False, hexes=None):
        self.calls.append(("aircraft", bbox, military, hexes))
        self._maybe_fail()
        return {"now": 1, "aircraft": [{"hex": "a37f12", "lat": 18.4, "lon": -66.0}],
                "coverage": {"mode": "point_radius", "complete": False}, "upstream_url": "https://api.test/v2/point/x"}

    def fetch_trace(self, hex_id, day=None):
        self.calls.append(("trace", hex_id, day))
        self._maybe_fail()
        return {"hex": hex_id, "points": [{"t": 1, "lat": 18, "lon": -66}], "upstream_url": "https://site.test/t"}

    def latest_complete_chunk_start(self):
        return LATEST

    def fetch_heatmap_chunk(self, moment):
        self.calls.append(("chunk", moment))
        self._maybe_fail()
        start = moment.replace(minute=(moment.minute // 30) * 30, second=0, microsecond=0).timestamp()
        slices = [
            {"timestamp": start + 10 * i, "interval_s": 10,
             "identities": [{"hex": "a37f12", "flight": "AAL1512", "squawk": "3037"}] if i == 0 else [],
             "positions": [{"hex": "a37f12", "lat": 18.4, "lon": -66.0 + i / 100, "alt_baro": 30000, "gs": 400.0, "source_type": "adsb_icao"},
                           {"hex": "c0ffee", "lat": 40.0, "lon": -73.0, "alt_baro": 1000, "gs": 100.0, "source_type": "mlat"}]}
            for i in range(180)
        ]
        return "globe_history/x/heatmap/32.bin.ttf", encode_heatmap(slices)

    def fetch_routes(self, planes):
        self._maybe_fail()
        return [{"callsign": planes[0]["callsign"]}]


@pytest.fixture
def client_with():
    def make(provider):
        app.dependency_overrides[live_router.get_live_provider] = lambda: provider
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def test_status_reports_feeds_and_openaip_credentials(client_with, monkeypatch):
    monkeypatch.delenv("OPENAIP_API_KEY", raising=False)
    body = client_with(FakeProvider()).get("/api/console/live/status").json()
    feeds = {feed["id"]: feed for feed in body["feeds"]}
    assert set(feeds) == {"adsblol.aircraft", "adsblol.military", "adsblol.trace", "adsblol.replay", "adsblol.routes", "openaip.tiles"}
    assert feeds["openaip.tiles"]["status"] == "missing_credentials"
    assert body["policy"]["bot_protected_endpoints_used"] is False
    monkeypatch.setenv("OPENAIP_API_KEY", "k")
    body = client_with(FakeProvider()).get("/api/console/live/status").json()
    assert body["openaip"]["configured"] is True


def test_aircraft_envelope_carries_provenance_and_coverage(client_with):
    provider = FakeProvider()
    response = client_with(provider).get("/api/console/live/aircraft", params={"bbox": "-68.2,17.8,-65.1,18.7", "hex": "A37F12", "military": "true"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available" and body["count"] == 1
    assert body["feed"] == "adsblol.military"
    assert body["source"]["license"] == "ODbL-1.0" and body["source"]["persisted"] is False
    assert "250 NM" in body["reason"]
    assert provider.calls[0] == ("aircraft", [-68.2, 17.8, -65.1, 18.7], True, ["a37f12"])


def test_aircraft_validation_and_upstream_failure(client_with):
    client = client_with(FakeProvider(fail=True))
    assert client.get("/api/console/live/aircraft", params={"bbox": "1,2,3"}).status_code == 422
    assert client.get("/api/console/live/aircraft", params={"bbox": "-68,17,-65,18", "hex": "nothex"}).status_code == 422
    body = client.get("/api/console/live/aircraft", params={"bbox": "-68,17,-65,18"}).json()
    assert body["status"] == "upstream_unavailable" and body["aircraft"] == []
    assert body["reason"] == live_router.UPSTREAM_REASON


def test_upstream_exception_text_never_reaches_clients(client_with):
    client = client_with(FakeProvider(fail=True))
    responses = [
        client.get("/api/console/live/aircraft", params={"bbox": "-68,17,-65,18"}),
        client.get("/api/console/live/trace/a37f12"),
        client.get("/api/console/live/replay", params={"ts": "2026-11-03T09:00:00Z", "bbox": "-68,17,-65,18"}),
        client.post("/api/console/live/routes", json={"planes": [{"callsign": "AAL1512"}]}),
    ]
    for response in responses:
        assert response.status_code == 200
        assert "internal.example" not in response.text and "upstream down" not in response.text


def test_not_found_and_decode_errors_map_to_fixed_reasons(client_with):
    missing = client_with(FakeProvider(fail=True, error=UpstreamNotFound("HTTP 404 for https://x/secret")))
    replay = missing.get("/api/console/live/replay", params={"ts": "2026-11-03T09:00:00Z", "bbox": "-68,17,-65,18"}).json()
    assert replay["reason"] == "adsb.lol has no replay data for this time."
    trace = missing.get("/api/console/live/trace/a37f12").json()
    assert trace["reason"] == "adsb.lol has no trace for this aircraft on this day."

    class BrokenChunk(FakeProvider):
        def fetch_heatmap_chunk(self, moment):
            return "x", b"\x00" * 32

    broken = client_with(BrokenChunk()).get("/api/console/live/replay", params={"ts": "2026-11-03T09:00:00Z", "bbox": "-68,17,-65,18"}).json()
    assert broken["status"] == "upstream_unavailable" and broken["reason"] == live_router.DECODE_REASON


def test_trace_endpoint(client_with):
    provider = FakeProvider()
    client = client_with(provider)
    body = client.get("/api/console/live/trace/a37f12", params={"date": "2026-11-01"}).json()
    assert body["status"] == "available" and body["points"]
    assert provider.calls[-1] == ("trace", "a37f12", date(2026, 11, 1))
    assert client.get("/api/console/live/trace/a37f12", params={"date": "yesterday"}).status_code == 422
    assert client_with(FakeProvider(fail=True)).get("/api/console/live/trace/a37f12").json()["status"] == "upstream_unavailable"


def test_replay_returns_bbox_frames_from_requested_time(client_with):
    client = client_with(FakeProvider())
    response = client.get("/api/console/live/replay", params={"ts": "2026-11-03T09:32:05Z", "bbox": "-68.2,17.8,-65.1,18.7", "window_s": 60})
    body = response.json()
    assert body["status"] == "available" and body["clamped_to_latest"] is False
    assert body["chunk"]["index"] == 19
    assert body["fields"][:3] == ["hex", "lat", "lon"]
    times = [frame["t"] for frame in body["frames"]]
    requested = datetime(2026, 11, 3, 9, 32, 5, tzinfo=timezone.utc).timestamp()
    assert times[0] <= requested < times[1]
    assert times[-1] < requested + 60
    rows = body["frames"][0]["aircraft"]
    assert rows == [["a37f12", 18.4, rows[0][2], 30000, 400.0, "adsb_icao", "AAL1512", "3037"]]


def test_replay_clamps_future_times_and_validates(client_with):
    client = client_with(FakeProvider())
    future = (LATEST + timedelta(hours=2)).isoformat()
    body = client.get("/api/console/live/replay", params={"ts": future, "bbox": "-68.2,17.8,-65.1,18.7"}).json()
    assert body["clamped_to_latest"] is True and body["ts_utc"] == "2026-11-03T16:01:00Z"
    assert client.get("/api/console/live/replay", params={"ts": "2026-11-03T09:00:00", "bbox": "-68,17,-65,18"}).status_code == 422
    failed = client_with(FakeProvider(fail=True)).get("/api/console/live/replay", params={"ts": "2026-11-03T09:00:00Z", "bbox": "-68,17,-65,18"}).json()
    assert failed["status"] == "upstream_unavailable" and failed["frames"] == []


def test_routes_endpoint(client_with):
    client = client_with(FakeProvider())
    assert client.post("/api/console/live/routes", json={"planes": "x"}).status_code == 422
    assert client.post("/api/console/live/routes", json={"planes": ["x"]}).status_code == 422
    body = client.post("/api/console/live/routes", json={"planes": [{"callsign": "AAL1512"}]}).json()
    assert body["status"] == "available" and body["routes"] == [{"callsign": "AAL1512"}]


def test_openaip_tile_requires_key_and_valid_coordinates(client_with, monkeypatch):
    client = client_with(FakeProvider())
    monkeypatch.delenv("OPENAIP_API_KEY", raising=False)
    assert client.get("/api/console/live/tiles/openaip/3/9/9.png").status_code == 422
    assert client.get("/api/console/live/tiles/openaip/3/-1/2.png").status_code == 422
    assert client.get("/api/console/live/tiles/openaip/3/%2E%2E/2.png").status_code == 422
    assert client.get("/api/console/live/tiles/openaip/3/1/1.png").status_code == 503
    monkeypatch.setenv("OPENAIP_API_KEY", "secret")
    captured = {}

    def fake_fetch(url, key):
        captured["url"], captured["key"] = url, key
        return b"\x89PNG"

    monkeypatch.setattr(live_router, "_fetch_openaip_tile", fake_fetch)
    response = client.get("/api/console/live/tiles/openaip/3/1/2.png")
    assert response.status_code == 200 and response.content == b"\x89PNG"
    assert captured == {"url": "https://api.tiles.openaip.net/api/data/openaip/3/1/2.png", "key": "secret"}
    assert "secret" not in response.headers.get("cache-control", "")

    def failing_fetch(url, key):
        raise OSError("connect to 10.0.0.5 refused")

    monkeypatch.setattr(live_router, "_fetch_openaip_tile", failing_fetch)
    failed = client.get("/api/console/live/tiles/openaip/3/1/2.png")
    assert failed.status_code == 502 and "10.0.0.5" not in failed.text


def test_replay_decoder_sanity_for_fake_chunk():
    _, data = FakeProvider().fetch_heatmap_chunk(datetime(2026, 11, 3, 9, 32, tzinfo=timezone.utc))
    assert len(decode_heatmap(data).slices) == 180
