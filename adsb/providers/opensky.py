"""
OpenSky Network provider (OAuth2 client credentials, anonymous fallback).

Thin wrapper around the official ``opensky-api`` Python client
(https://github.com/openskynetwork/opensky-api). That client owns its own
HTTP/token handling (``OpenSkyApi`` + ``TokenManager``); this module only
adapts its bbox convention and result shape to this repo's ``StateVector``
and raises :class:`ProviderError` uniformly on failure.

Install: pip install "git+https://github.com/openskynetwork/opensky-api.git#subdirectory=python"
"""

from __future__ import annotations

from .. import config
from ..models import StateVector
from .base import AdsbProvider, ProviderError


class OpenSkyProvider(AdsbProvider):
    """Live state vectors from the OpenSky Network REST API."""

    name = "opensky"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        self.client_id = config.OPENSKY_CLIENT_ID if client_id is None else client_id
        self.client_secret = (
            config.OPENSKY_CLIENT_SECRET if client_secret is None else client_secret
        )
        self._api = None

    def _client(self):
        """Lazily construct the underlying ``OpenSkyApi`` client.

        Credentials are optional: OpenSky serves anonymous requests at a
        reduced rate limit, so a missing client id/secret is not an error
        here (unlike the imagery OAuth2 providers, which require creds).
        """
        if self._api is not None:
            return self._api
        try:
            from opensky_api import OpenSkyApi
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ProviderError(
                "opensky-api is not installed; run: uv sync --extra adsb"
            ) from exc
        if self.client_id and self.client_secret:
            self._api = OpenSkyApi(client_id=self.client_id, client_secret=self.client_secret)
        else:
            self._api = OpenSkyApi()
        return self._api

    def fetch_states(self, bbox: list[float]) -> list[StateVector]:
        west, south, east, north = bbox[:4]
        # OpenSky's bbox order is (min_lat, max_lat, min_lon, max_lon) —
        # different from this repo's (west, south, east, north) convention.
        opensky_bbox = (south, north, west, east)
        try:
            response = self._client().get_states(bbox=opensky_bbox)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - client raises plain Exception/OSError
            raise ProviderError(f"opensky get_states failed: {exc}") from exc
        if response is None or response.states is None:
            return []
        return [self._to_state_vector(s) for s in response.states]

    def _to_state_vector(self, s) -> StateVector:
        return StateVector(
            icao24=s.icao24,
            callsign=(s.callsign or "").strip() or None,
            origin_country=s.origin_country,
            time_position=s.time_position,
            last_contact=s.last_contact,
            longitude=s.longitude,
            latitude=s.latitude,
            baro_altitude=s.baro_altitude,
            on_ground=bool(s.on_ground),
            velocity=s.velocity,
            true_track=s.true_track,
            vertical_rate=s.vertical_rate,
            geo_altitude=s.geo_altitude,
            squawk=s.squawk,
            position_source=s.position_source,
            provider=self.name,
        )
