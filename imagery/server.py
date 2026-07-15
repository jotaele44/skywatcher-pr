"""
Imagery MCP server (FastMCP).

Exposes three tools over MCP:

  * ``fetch_imagery(lat, lon, date_range, provider)``     — pull an image + cloud%
  * ``query_imagery_metadata(bbox, date_range, provider)``— catalog search, no pixels
  * ``compare_imagery(lat, lon, date1, date2, provider)`` — lightweight change detection

Providers: ``gibs`` (no auth, default), ``sentinelhub`` (OAuth2), ``copernicus`` (CDSE OAuth2).

Run (stdio, the default agent-loop transport):
    python -m imagery.server
Run (SSE):
    python -m imagery.server --transport sse --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

from typing import Any, Optional

from . import compare as compare_mod
from . import config, sink
from .providers import ProviderError, available_providers, get_provider

TOOL_NAMES = ["fetch_imagery", "query_imagery_metadata", "compare_imagery"]


def list_tool_names() -> list[str]:
    """Names of the tools this server registers (used by smoke tests)."""
    return list(TOOL_NAMES)


# ── tool implementations (plain functions, directly unit-testable) ────────────
def fetch_imagery(
    lat: float,
    lon: float,
    date_range: str,
    provider: str = "gibs",
    buffer_deg: Optional[float] = None,
    image_size: Optional[int] = None,
    persist: bool = True,
    include_image: bool = True,
) -> dict[str, Any]:
    """Fetch a satellite image for a point over a date range.

    Args:
        lat, lon: WGS84 coordinates of the area of interest.
        date_range: ``"YYYY-MM-DD/YYYY-MM-DD"`` or a single ``"YYYY-MM-DD"``.
        provider: ``gibs`` | ``sentinelhub`` | ``copernicus``.
        buffer_deg: half-width in degrees of the bbox around the point.
        image_size: output raster size in pixels (square).
        persist: if true, route the tile metadata through the satellite-manifest
            ingest pipeline so it is indexed alongside other spatial records.
        include_image: include the base64-encoded image in the response.

    Returns a dict with image metadata (+ optional ``image_base64``), the local
    ``cache_path``, ``cloud_cover_pct`` (may be null for GIBS composites), and,
    when ``persist``, a ``persisted`` block describing the ingest outcome.
    """
    try:
        prov = get_provider(provider)
        result = prov.fetch_point(
            lat, lon, date_range, buffer_deg=buffer_deg, image_size=image_size
        )
    except ProviderError as exc:
        return {"ok": False, "error": str(exc), "provider": provider}

    out: dict[str, Any] = {"ok": True, **result.to_dict(include_image=include_image)}
    if persist:
        out["persisted"] = sink.persist(result)
    return out


def query_imagery_metadata(
    bbox: list[float],
    date_range: str,
    provider: str = "sentinelhub",
    max_items: int = 10,
) -> dict[str, Any]:
    """Catalog/STAC search over a bbox + date range — metadata only, no imagery.

    Args:
        bbox: ``[west, south, east, north]`` in EPSG:4326.
        date_range: ``"YYYY-MM-DD/YYYY-MM-DD"`` or a single date.
        provider: ``gibs`` | ``sentinelhub`` | ``copernicus``.
        max_items: maximum scenes to return.

    Returns ``{provider, count, scenes: [...]}`` where each scene carries id,
    datetime, collection, cloud cover, bbox, and thumbnail (when available).
    """
    try:
        prov = get_provider(provider)
        scenes = prov.search(bbox, date_range, max_items=max_items)
    except ProviderError as exc:
        return {"ok": False, "error": str(exc), "provider": provider}
    return {
        "ok": True,
        "provider": provider,
        "count": len(scenes),
        "scenes": [s.to_dict() for s in scenes],
    }


def compare_imagery(
    lat: float,
    lon: float,
    date1: str,
    date2: str,
    provider: str = "gibs",
    buffer_deg: Optional[float] = None,
    image_size: Optional[int] = None,
    threshold: Optional[float] = None,
    include_images: bool = False,
) -> dict[str, Any]:
    """Fetch the same footprint on two dates and report a change metric.

    Returns ``changed_pct`` (fraction of pixels whose normalized grayscale
    difference exceeds ``threshold``) plus both images' metadata. Change
    detection is intentionally lightweight (Pillow/NumPy, no GDAL).
    """
    try:
        prov = get_provider(provider)
        r1 = prov.fetch_point(
            lat, lon, date1, buffer_deg=buffer_deg, image_size=image_size
        )
        r2 = prov.fetch_point(
            lat, lon, date2, buffer_deg=buffer_deg, image_size=image_size
        )
        change = compare_mod.changed_fraction(r1, r2, threshold=threshold)
    except ProviderError as exc:
        return {"ok": False, "error": str(exc), "provider": provider}
    return {"ok": True, **change.to_dict(include_images=include_images)}


# ── FastMCP wiring ────────────────────────────────────────────────────────────
def build_server():
    """Construct and return the FastMCP app with all three tools registered."""
    from fastmcp import FastMCP

    mcp = FastMCP(
        "imagery",
        instructions=(
            "Satellite imagery tools for the Puerto Rico AOI. Providers: "
            f"{', '.join(available_providers())}. GIBS needs no credentials; "
            "sentinelhub/copernicus require OAuth2 client id/secret env vars."
        ),
    )
    for fn in (fetch_imagery, query_imagery_metadata, compare_imagery):
        try:
            mcp.tool(fn)
        except TypeError:  # pragma: no cover - older/newer FastMCP signatures
            mcp.add_tool(fn)
    return mcp


def main(argv: Optional[list[str]] = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Imagery MCP server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "sse"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    mcp = build_server()
    if args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
