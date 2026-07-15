"""
Copernicus Data Space Ecosystem (CDSE) provider.

CDSE hosts a Sentinel-Hub-compatible Process/Catalog API, so this provider is a
thin subclass of :class:`SentinelHubStyleProvider` pointed at the CDSE hosts and
identity server. Credentials come from ``COPERNICUS_CLIENT_ID`` /
``COPERNICUS_CLIENT_SECRET``.

Docs: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/
"""

from __future__ import annotations

from .. import config
from .sentinelhub import SentinelHubStyleProvider


class CopernicusProvider(SentinelHubStyleProvider):
    name = "copernicus"
    base_url = config.COPERNICUS_BASE_URL
    token_url = config.COPERNICUS_TOKEN_URL
    client_id = config.COPERNICUS_CLIENT_ID
    client_secret = config.COPERNICUS_CLIENT_SECRET
    collection = config.COPERNICUS_COLLECTION
