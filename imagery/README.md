# Imagery MCP server

A [FastMCP](https://github.com/jlowin/fastmcp) server that wraps three satellite
imagery providers behind MCP tools and routes fetched-tile metadata into the
repository's satellite-manifest ingest pipeline (so imagery is indexed alongside
other spatial records).

## Tools

| Tool | Signature | Notes |
|------|-----------|-------|
| `fetch_imagery` | `(lat, lon, date_range, provider="gibs", ...)` | Returns image (base64) + `cloud_cover_pct` + `cache_path`; persists a manifest by default. |
| `query_imagery_metadata` | `(bbox, date_range, provider="sentinelhub", max_items=10)` | Catalog/STAC search, metadata only (no pixels). |
| `compare_imagery` | `(lat, lon, date1, date2, provider="gibs", ...)` | Lightweight change metric (`changed_pct`) between two dates. |

`date_range` is `"YYYY-MM-DD/YYYY-MM-DD"` or a single `"YYYY-MM-DD"`.

## Providers

| Provider | Auth | Cloud cover | Notes |
|----------|------|-------------|-------|
| `gibs` (NASA GIBS) | none | not available | Daily global composites via WMS GetMap. Default. |
| `sentinelhub` | OAuth2 client credentials | via Catalog `eo:cloud_cover` | Sentinel-2 L2A true-color via Process API. |
| `copernicus` (CDSE) | OAuth2 client credentials | via Catalog `eo:cloud_cover` | Sentinel-Hub-compatible CDSE hosts. |

## Install

```bash
pip install -e ".[imagery]"      # spiderweb-pr (extra)
# or
pip install -r requirements-imagery.txt
```

## Configuration (environment variables)

```bash
# Sentinel Hub
export SENTINELHUB_CLIENT_ID=...
export SENTINELHUB_CLIENT_SECRET=...
# Copernicus Data Space Ecosystem
export COPERNICUS_CLIENT_ID=...
export COPERNICUS_CLIENT_SECRET=...
```

Optional knobs (defaults in `imagery/config.py`): `IMAGERY_CACHE_DIR`,
`IMAGERY_BUFFER_DEG`, `IMAGERY_IMAGE_SIZE`, `IMAGERY_DEFAULT_PROVIDER`,
`IMAGERY_GIBS_LAYER`, `IMAGERY_CHANGE_THRESHOLD`. GIBS works with no credentials.

## Run

```bash
python -m imagery.server                                   # stdio (default)
python -m imagery.server --transport sse --host 127.0.0.1 --port 8765
```

### MCP client config (stdio)

```json
{
  "mcpServers": {
    "imagery": { "command": "python", "args": ["-m", "imagery.server"] }
  }
}
```

## Notes

- Fetched images are cached under `tile_cache/imagery/` (git-ignored),
  content-addressed by request parameters.
- Footprints are clamped to the Puerto Rico AOI envelope so generated manifests
  satisfy `schemas/satellite_source_manifest.schema.json`.
- Change detection is a first-pass grayscale-difference signal, not a calibrated
  product.
