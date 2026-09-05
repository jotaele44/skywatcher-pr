# GIS capability roadmap

## Shipped

The dashboard's map (`frontend/src/components/skywatcher/PuertoRicoMapShell.jsx`)
is a MapLibre GL map, replacing the earlier hand-rolled SVG/`projectToShell`
projection. It renders:

- Observations, airports, and infrastructure assets as GeoJSON Point layers
  (from props, converted client-side).
- Restricted-airspace zones and flight corridors (`gis_intelligence.py`'s
  `PuertoRicoInfrastructure` / `CorridorAnalyzer`) as real buffered GeoJSON
  Polygons, served by `server/backend/main.py`'s `/api/geo/infrastructure.geojson`
  and `/api/geo/corridors.geojson` — previously these existed only as
  lat/lon+radius and start/end+width tuples used for internal anomaly-detection
  math, never rendered.
- An observation density heatmap (`/api/geo/observations/heatmap.geojson`,
  wired to `HeatmapGenerator`), toggleable alongside the point layer.
- Per-aircraft ADS-B tracks as GeoJSON LineStrings
  (`/api/geo/tracks/{icao24}.geojson`), reusing the same track-building logic
  (`_line_string()`) as the Spiderweb bridge export. This degrades to an empty
  FeatureCollection when no ADS-B poller has run yet (the normal diagnostic
  state) rather than erroring.

## Deferred: SATIM raster layer

The SATIM satellite-imagery classification pipeline (`satim_*.py`) scores
pixel-space grid cells (`schemas/pr_grid_cell.txt`: a 256×384 pixel grid,
classified `Water_or_Empty` / `Gridline_Dominant` / `Coastline_or_Land`) but
those cells are not yet bound to real-world coordinates. Real lat/lon only
enters via `schemas/satim/satim_gis_join_ledger.schema.json` and the
dependency-free bbox helper in
`tools/satim_engine/src/satim_engine/plugins/gis_geometry.py`.

Serving SATIM output as a map raster/tile layer requires a georeferencing pass
(pixel↔lat/lon calibration per source screenshot) before it can be exposed as
a `raster` MapLibre source. That calibration work is tracked separately and is
out of scope for the GIS-visualization work described above.
