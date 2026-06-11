# GIS Export Guide

How to consume the pipeline's GeoJSON outputs in QGIS, Google Earth, and other GIS tools.

All spatial outputs use **EPSG:4326** (WGS-84 lat/lon). The `crs` member is declared inline in every FeatureCollection.

---

## What ships

The pipeline emits these GeoJSON artifacts (per [`SCHEMA_AND_EXPORT_CONTRACTS.md`](SCHEMA_AND_EXPORT_CONTRACTS.md)):

| File | Geometry | Schema | Contents |
|---|---|---|---|
| `gis_airspace_features.geojson` | `Point` | `gis_feature` | Airport nodes (origin + destination per flight, deduped) |
| `route_lines.geojson` | `LineString` | `gis_feature` | Origin→destination route lines per flight |
| `spiderweb_overlay_candidates.geojson` | `Point` | `spiderweb_observation` | Normalized POI / ILAP / corridor / AASB-edge candidates |
| `airspace_poi_candidates.geojson` | `Point` | `spiderweb_observation` | Raw POI candidates from the producer |
| `airspace_ilap_candidates.geojson` | `Point` / `LineString` | `ilap_corridor_candidate` | ILAP track candidates |
| `airspace_corridor_candidates.geojson` | `LineString` | `ilap_corridor_candidate` | Corridor candidates |

All carry per-feature **provenance** (`screenshot_id`, `sha256`, `source_path`) plus type-specific properties — see the relevant schema for the full list. The ILAP artifacts additionally carry a `properties._meta` block (`producer_module`, `source_artifact`, `produced_at`) so a single feature is self-describing, and each FeatureCollection stamps an explicit `epsg: 4326` alongside the OGC `crs` URN.

The ILAP bridge also writes a native **`.kml`** sibling next to each `.geojson` (e.g. `airspace_corridor_candidates.kml`) — see [Google Earth Pro](#google-earth-pro).

---

## QGIS

### Importing

1. **Drag-and-drop** the `.geojson` file from Finder/Explorer onto the QGIS map canvas.
2. QGIS auto-detects EPSG:4326 from the inline `crs` member — verify in the Layers panel (right-click → Properties → Source → CRS).
3. If the file is large (the full `screenshot_evidence` mirror can be ~50 MB), set rendering to "Render Layer Without Caching" the first time to avoid the cache-build pause.

### Ready-made styles (`.qml`)

The repo ships QGIS layer styles under [`styles/`](../styles) — load via right-click layer → Properties → Symbology → Style ▾ → Load Style:

| Layer | Style file | Renders by |
|---|---|---|
| `airspace_poi_candidates` | `styles/airspace_poi_candidates.qml` | `review_priority` (HIGH/MEDIUM/LOW) |
| `airspace_corridor_candidates` | `styles/airspace_corridor_candidates.qml` | `corridor_label` (HIGH/MEDIUM/LOW activity) |
| `aasb_airspace_edges` | `styles/aasb_airspace_edges.qml` | graduated on `weight` (flight count) |

For `aasb_airspace_edges.csv`, add it as a **Delimited Text** layer with geometry from `from_lat`/`from_lon` (point) or build lines from the four coordinate columns, then load the `.qml`.

### Symbology hints

- **Airport nodes** (`gis_airspace_features.geojson`): style by `properties.type` (currently always `"airport"`). Suggest a black-outlined yellow circle, 4 mm. Label by `properties.name`.
- **Route lines** (`route_lines.geojson`): style line width by `properties.duration_min` (longer flights = thicker). Categorize by `properties.callsign` for operator-color coding.
- **Spiderweb candidates** (`spiderweb_overlay_candidates.geojson`): categorize by `properties.evidence_tier` (T1 red, T2 orange, T3 yellow, T4 grey). Filter by `properties.mbil_class` to inspect built-up areas.
- **ILAP candidates**: style by `properties.overall_confidence` (graduated, 0–1).

### Joining with provenance

Every feature has `properties.screenshot_id` and `properties.source_path`. To audit a feature back to its source screenshot:

1. Open the feature's Attribute Table.
2. Copy `source_path` (e.g. `data/FR24_baseline/2025-08/2025-08-16T04-04-50_ec16e576.png`).
3. The path is relative to the repo root.

---

## Google Earth Pro

Google Earth doesn't read GeoJSON natively — it consumes KML/KMZ.

### Native KML export (in-pipeline)

The ILAP bridge now emits a **`.kml` sibling** next to every `.geojson` it writes
(`integration/kml_export.py`, T7-58). No external tooling required — just
**File → Open** the `.kml` (e.g. `airspace_corridor_candidates.kml`) in Google
Earth Pro. Feature properties travel as `<ExtendedData>`, so attributes are
visible in the placemark balloon.

### Notes

- The KML writer is dependency-free and supports `Point` and `LineString`
  geometries — the two types the airspace bridges produce. Coordinates are
  `lon,lat` (EPSG:4326), the same axis order as GeoJSON.
- The nested `_meta` block is intentionally omitted from `<ExtendedData>` (it is
  not a flat scalar); all other properties round-trip.

> **Deprecated (T7-63):** the previous `ogr2ogr -f KML …` workaround is no longer
> needed now that native KML ships in-pipeline. It remains a valid fallback for
> the `pr_intel_adapter` artifacts (`route_lines.geojson`,
> `gis_airspace_features.geojson`), which do not yet emit KML siblings.

---

## Other tools

- **Mapbox Studio / MapLibre GL**: GeoJSON loads directly via the API. Use the `crs` member to confirm projection; set `cluster: true` on the airport-nodes source for clean zoom-out display.
- **Folium (Python notebook)**: `folium.GeoJson(path)` — set `style_function` to color by `properties.evidence_tier`. Use `tooltip=folium.GeoJsonTooltip(['name', 'callsign', 'evidence_tier'])` for inspect-on-hover.
- **kepler.gl**: drag-drop works; the auto-config defaults to a heatmap visualization. Manually switch to "GeoJSON" layer type for route lines.

---

## Validation

After importing into any GIS tool, sanity-check:

- **CRS** is EPSG:4326 (the loaded layer should show coordinates around `lon ≈ -67..-65`, `lat ≈ 17.5..18.6` for PR airspace).
- **Feature count** matches `source_manifest.json` → the relevant artifact's `geo_summary.feature_count`.
- **Bbox** matches `source_manifest.json` → `geo_summary.bbox` (the FeatureCollection extent is computed by `provenance_utils.feature_collection_summary()`).

If any of these drifts, the upstream pipeline likely emitted a stale artifact — re-run `--export-pr-intel` or `--export-spiderweb`.

---

## Cross-references

- [`SCHEMA_AND_EXPORT_CONTRACTS.md`](SCHEMA_AND_EXPORT_CONTRACTS.md) — per-artifact schema.
- [`SPIDERWEB_LANGUAGE_BRIDGE.md`](SPIDERWEB_LANGUAGE_BRIDGE.md) — canonical vocabulary for property values.
- [`RELEASE_READINESS.md`](RELEASE_READINESS.md) — gate that ensures these files are produced.
