"""Tests for the adsb.lol provider with a fake HTTP opener (no network)."""

import gzip
import json
from datetime import date, datetime, timezone

import pytest

from adsb.heatmap import encode_heatmap
from adsb.providers import ProviderError, available_providers, get_provider
from adsb.providers.adsblol import (
    AdsbLolProvider,
    UpstreamNotFound,
    bbox_query_circle,
    decode_trace,
    normalize_hex,
)

PR_BBOX = [-68.2, 17.8, -65.1, 18.7]
NOW = datetime(2026, 11, 3, 16, 32, tzinfo=timezone.utc).timestamp()

AC_IN = {"hex": "a37f12", "flight": "AAL1512 ", "lat": 18.4, "lon": -66.0, "alt_baro": 36000,
         "alt_geom": 36500, "gs": 430.0, "track": 90.0, "baro_rate": 1000, "squawk": "3037",
         "seen": 0.4, "seen_pos": 0.9, "t": "B738", "r": "N123AA"}
AC_OUT = {"hex": "c0ffee", "lat": 40.6, "lon": -73.8, "alt_baro": 5000}


class FakeOpener:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, request, timeout):
        url = request.full_url
        self.calls.append((request.get_method(), url, request.data))
        for prefix, response in self.routes.items():
            if url.startswith(prefix):
                status, headers, body = response
                return status, headers, body
        raise AssertionError(f"unexpected request {url}")


def _json(payload, gz=False):
    raw = json.dumps(payload).encode()
    if gz:
        return 200, {"content-encoding": "gzip"}, gzip.compress(raw)
    return 200, {}, raw


def _provider(routes, tmp_path):
    opener = FakeOpener(routes)
    provider = AdsbLolProvider(api_base="https://api.test", site_base="https://site.test",
                               cache_dir=tmp_path, opener=opener, clock=lambda: NOW)
    return provider, opener


def test_registry_exposes_adsblol():
    assert "adsblol" in available_providers()
    assert isinstance(get_provider("adsb.lol"), AdsbLolProvider)


def test_bbox_query_circle_covers_corners_and_caps_radius():
    circle = bbox_query_circle(PR_BBOX, 250)
    assert circle["complete"] is True
    assert circle["lat"] == pytest.approx(18.25)
    assert circle["lon"] == pytest.approx(-66.65)
    assert 90 < circle["radius_nm"] <= 250
    wide = bbox_query_circle([-80, 10, -60, 30], 250)
    assert wide["radius_nm"] == 250 and wide["complete"] is False
    with pytest.raises(ProviderError):
        bbox_query_circle([0, 10, 1, 5], 250)


def test_fetch_aircraft_filters_to_bbox_and_adds_selected_hex(tmp_path):
    provider, opener = _provider({
        "https://api.test/v2/point/": _json({"ac": [AC_IN, AC_OUT], "now": NOW * 1000, "total": 2}),
        "https://api.test/v2/hex/c0ffee": _json({"ac": [AC_OUT]}),
    }, tmp_path)
    result = provider.fetch_aircraft(PR_BBOX, hexes=["C0FFEE"])
    assert [ac["hex"] for ac in result["aircraft"]] == ["a37f12", "c0ffee"]
    assert result["aircraft"][1]["outside_view"] is True
    assert result["coverage"]["mode"] == "point_radius"
    assert opener.calls[0][1].startswith("https://api.test/v2/point/18.25/-66.65/")


def test_fetch_aircraft_military_uses_mil_endpoint(tmp_path):
    provider, opener = _provider({"https://api.test/v2/mil": _json({"ac": [AC_IN, AC_OUT]}, gz=True)}, tmp_path)
    result = provider.fetch_aircraft(PR_BBOX, military=True)
    assert [ac["hex"] for ac in result["aircraft"]] == ["a37f12"]
    assert result["coverage"] == {"mode": "military_global", "complete": True}
    assert opener.calls[0][1] == "https://api.test/v2/mil"


def test_identical_requests_are_memoised_within_ttl(tmp_path):
    provider, opener = _provider({"https://api.test/v2/point/": _json({"ac": [AC_IN]})}, tmp_path)
    provider.fetch_aircraft(PR_BBOX)
    provider.fetch_aircraft(PR_BBOX)
    assert len(opener.calls) == 1


def test_fetch_states_converts_to_si_units(tmp_path):
    provider, _ = _provider({"https://api.test/v2/point/": _json({"ac": [AC_IN], "now": NOW * 1000})}, tmp_path)
    (state,) = provider.fetch_states(PR_BBOX)
    assert state.provider == "adsblol"
    assert state.callsign == "AAL1512"
    assert state.baro_altitude == pytest.approx(36000 * 0.3048, abs=0.01)
    assert state.velocity == pytest.approx(430 * 0.514444, abs=0.01)
    assert state.vertical_rate == pytest.approx(1000 * 0.00508, abs=0.01)
    assert state.on_ground is False
    assert state.time_position == int(NOW - 0.9)


def test_fetch_trace_selects_live_or_history_path(tmp_path):
    payload = {"icao": "a37f12", "r": "N123AA", "t": "B738", "timestamp": 1000.0,
               "trace": [[0, 18.0, -66.0, 1000, 200, 90, 2, 0, {"flight": "AAL1 "}, "adsb_icao", 1100],
                         [10, 18.1, -66.1, "ground", 0, 90, 1, None, None, "mlat", None]]}
    provider, opener = _provider({
        "https://site.test/data/traces/12/trace_full_a37f12.json": _json(payload, gz=True),
        "https://site.test/globe_history/2026/11/01/traces/12/trace_full_a37f12.json": _json(payload),
    }, tmp_path)
    live = provider.fetch_trace("a37f12")
    assert live["points"][0]["new_leg"] is True and live["points"][0]["flight"] == "AAL1"
    assert live["points"][1]["t"] == 1010.0 and live["points"][1]["stale"] is True
    provider.fetch_trace("a37f12", date(2026, 11, 1))
    assert opener.calls[-1][1].endswith("globe_history/2026/11/01/traces/12/trace_full_a37f12.json")
    with pytest.raises(ProviderError):
        provider.fetch_trace("../etc")


def test_heatmap_chunks_cache_only_when_complete(tmp_path):
    body = encode_heatmap([{"timestamp": NOW - 3600, "interval_s": 10, "positions": []}])
    provider, opener = _provider({"https://site.test/globe_history/": (200, {"content-encoding": "gzip"}, gzip.compress(body))}, tmp_path)
    old = datetime(2026, 11, 3, 15, 5, tzinfo=timezone.utc)
    rel, data = provider.fetch_heatmap_chunk(old)
    assert rel == "globe_history/2026/11/03/heatmap/30.bin.ttf" and data == body
    assert (tmp_path / rel).read_bytes() == body
    current = datetime(2026, 11, 3, 16, 31, tzinfo=timezone.utc)
    rel_now, _ = provider.fetch_heatmap_chunk(current)
    assert not (tmp_path / rel_now).exists()
    assert provider.latest_complete_chunk_start() == datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)


def test_routes_are_sanitised_before_posting(tmp_path):
    airports = [{"iata": "SJU", "icao": "TJSJ", "location": "San Juan"}, {"iata": "MIA", "icao": "KMIA", "location": "Miami"}]
    provider, opener = _provider({"https://api.test/api/0/routeset": _json([{"callsign": "AAL1512", "_airports": airports, "plausible": True}])}, tmp_path)
    routes = provider.fetch_routes([{"callsign": "aal1512", "lat": 18.4, "lng": -66}, {"callsign": "bad callsign!"}])
    assert routes[0]["callsign"] == "AAL1512"
    assert routes[0]["route"] == "SJU - MIA" and routes[0]["cities"] == "San Juan - Miami"
    method, _, body = opener.calls[0]
    assert method == "POST"
    assert json.loads(body) == {"planes": [{"callsign": "AAL1512", "lat": 18.4, "lng": -66.0}]}
    assert provider.fetch_routes([{"callsign": ""}]) == []


def test_routes_empty_body_means_no_known_route(tmp_path):
    provider, _ = _provider({"https://api.test/api/0/routeset": (201, {}, b"")}, tmp_path)
    assert provider.fetch_routes([{"callsign": "AAL1512", "lat": 18.4, "lng": -66}]) == []


def test_http_errors_raise_provider_error(tmp_path):
    provider, _ = _provider({"https://api.test/v2/point/": (500, {}, b"boom")}, tmp_path)
    with pytest.raises(ProviderError):
        provider.fetch_aircraft(PR_BBOX)
    missing, _ = _provider({"https://site.test/": (404, {}, b"")}, tmp_path)
    with pytest.raises(UpstreamNotFound):
        missing.fetch_trace("a37f12")


def test_normalize_hex_and_decode_trace_edge_cases():
    assert normalize_hex(" ~ABC123 ") == "~abc123"
    with pytest.raises(ProviderError):
        normalize_hex("zzzzzz")
    assert decode_trace({"trace": [None, [1, 2]]})["points"] == []
