"""
Imagery — satellite-imagery fetch/search/compare tools exposed over MCP.

A self-contained package that wraps NASA GIBS, Sentinel Hub, and Copernicus
(CDSE) behind a small provider interface, caches fetched tiles locally, and
routes fetched-tile metadata into the repository's satellite-manifest pipeline
(see ``imagery.sink``).

Entry point: ``python -m imagery.server`` (FastMCP; stdio by default).
"""

from .models import ChangeResult, ImageryResult, SceneMetadata

__all__ = ["ImageryResult", "SceneMetadata", "ChangeResult"]
