"""
Tests for the ADS-B (OpenSky) provider (mocked client; no network).

``OpenSkyProvider._client`` is monkeypatched with a fake ``OpenSkyApi``-shaped
object so we exercise bbox translation and StateVector mapping without
hitting the live OpenSky service. A single ``@pytest.mark.integration`` test
hits the real (anonymous) OpenSky endpoint and is excluded from the default
``-m 'not integration'`` run.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("opensky_api")

from adsb.providers import ProviderError, get_provider
from adsb.providers.opensky import OpenSkyProvider

PR_BBOX = [-68.2, 17.8, -65.1, 18.7]  # west, south, east, north


def _fake_state(**overrides):
    base = dict(
        icao24="a1b2c3",
        callsign="N767PD  ",
        origin_country="United States",
        time_position=1700000000,
        last_contact=1700000005,
        longitude=-66.4,
        latitude=18.2,
        baro_altitude=1500.0,
        on_ground=False,
        velocity=120.5,
        true_track=270.0,
        vertical_rate=0.0,
        geo_altitude=1520.0,
        squawk="1200",
        position_source=0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeStatesResponse:
    def __init__(self, states):
        self.states = states


def test_fetch_states_translates_bbox_order(monkeypatch):
    prov = OpenSkyProvider()
    captured = {}

    class FakeApi:
        def get_states(self, bbox=()):
            captured["bbox"] = bbox
            return FakeStatesResponse([_fake_state()])

    monkeypatch.setattr(prov, "_client", lambda: FakeApi())
    prov.fetch_states(PR_BBOX)

    west, south, east, north = PR_BBOX
    assert captured["bbox"] == (south, north, west, east)


def test_fetch_states_maps_state_vector_fields(monkeypatch):
    prov = OpenSkyProvider()
    monkeypatch.setattr(
        prov,
        "_client",
        lambda: SimpleNamespace(get_states=lambda bbox=(): FakeStatesResponse([_fake_state()])),
    )

    states = prov.fetch_states(PR_BBOX)
    assert len(states) == 1
    sv = states[0]
    assert sv.icao24 == "a1b2c3"
    assert sv.callsign == "N767PD"  # stripped
    assert sv.latitude == 18.2
    assert sv.longitude == -66.4
    assert sv.on_ground is False
    assert sv.provider == "opensky"


def test_fetch_states_blank_callsign_becomes_none(monkeypatch):
    prov = OpenSkyProvider()
    monkeypatch.setattr(
        prov,
        "_client",
        lambda: SimpleNamespace(
            get_states=lambda bbox=(): FakeStatesResponse([_fake_state(callsign="   ")])
        ),
    )
    states = prov.fetch_states(PR_BBOX)
    assert states[0].callsign is None


def test_fetch_states_empty_response(monkeypatch):
    prov = OpenSkyProvider()
    monkeypatch.setattr(
        prov,
        "_client",
        lambda: SimpleNamespace(get_states=lambda bbox=(): FakeStatesResponse(None)),
    )
    assert prov.fetch_states(PR_BBOX) == []


def test_fetch_states_wraps_client_errors(monkeypatch):
    prov = OpenSkyProvider()

    def boom(bbox=()):
        raise OSError("network unreachable")

    monkeypatch.setattr(prov, "_client", lambda: SimpleNamespace(get_states=boom))
    with pytest.raises(ProviderError):
        prov.fetch_states(PR_BBOX)


def test_client_used_anonymously_without_credentials():
    prov = OpenSkyProvider(client_id="", client_secret="")
    api = prov._client()
    assert api is not None
    # Second call reuses the same lazily-constructed client.
    assert prov._client() is api


# ── registry ──────────────────────────────────────────────────────────────────
def test_registry_resolves_opensky():
    assert get_provider("opensky").name == "opensky"
    assert get_provider("OpenSky-Network").name == "opensky"


def test_registry_unknown_raises():
    with pytest.raises(ProviderError):
        get_provider("nope")


# ── live (excluded from default runs) ─────────────────────────────────────────
@pytest.mark.integration
def test_opensky_live_fetch_anonymous():
    prov = OpenSkyProvider(client_id="", client_secret="")
    states = prov.fetch_states(PR_BBOX)
    assert isinstance(states, list)
