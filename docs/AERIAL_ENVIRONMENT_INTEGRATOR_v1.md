# Skywatcher Aerial Environment Integrator v1

Status: PROVISIONAL / implementation contract

## Role

Skywatcher is the Federation **AERIAL_ENVIRONMENT_INTEGRATOR** for aviation-facing environmental context and 4D visualization. It is not the universal scientific authority for weather, geomagnetism, air quality, radar, satellite, or space-weather products.

Authoritative providers remain authoritative for their source products, including NOAA/NWS/NESDIS/AWC/NCEI, USGS, EPA, and other explicitly admitted public-official sources.

## Mandatory semantic states

Every environmental product MUST declare exactly one semantic state:

- `measured`
- `forecast`
- `modeled`
- `interpolated`
- `derived`

No adapter may silently promote one state into another. Forecasts are not observations. Station measurements are not spatial fields. Satellite aerosol optical depth is not PM2.5. Geomagnetic excursions do not establish radar or aircraft causation.

## Mandatory map manifestation

Aerial-environment capability is incomplete unless a real interactive GIS map is reachable from the operator surface.

The primary map manifestation MUST support:

- pan and zoom;
- explicit layer visibility;
- point, line, polygon, heatmap, raster, and DEM-compatible layers where applicable;
- UTC-aware time filtering for time-indexed products;
- source/semantic-state inspection;
- stale/gap indication;
- observation and airport/airspace context without proximity-as-identity inference;
- raster and vector provenance binding;
- offline-safe degradation where remote visual context is unavailable.

A static SVG, screenshot, chart, or provider-rendered frame is not equivalent to the primary GIS map manifestation.

## Initial source-family candidates

| Family | Candidate authority | Initial state |
|---|---|---|
| aviation weather | NOAA/NWS Aviation Weather Center | CANDIDATE_PUBLIC_OFFICIAL |
| geomagnetism | USGS Geomagnetism Program / SJG | CANDIDATE_PUBLIC_OFFICIAL |
| air quality current context | EPA AirNow | CANDIDATE_PUBLIC_OFFICIAL |
| air quality historical/regulatory | EPA AQS/AirData | CANDIDATE_PUBLIC_OFFICIAL |
| weather radar | NOAA/NCEI NEXRAD TJUA | CANDIDATE_PUBLIC_OFFICIAL |
| satellite / lightning | NOAA/NESDIS GOES ABI/GLM | CANDIDATE_PUBLIC_OFFICIAL |

Candidate status is not production admission. Each source requires explicit access, terms/licensing, product identity, temporal semantics, provenance, regression gates, and bounded certification.

## Federation boundary

- Skywatcher owns aerial-environment normalization, aviation-facing analysis, and map/replay production.
- External scientific providers own source-product authority.
- GIS Cloud may be used for noncanonical visual/spatial QA only and MUST NOT become a required runtime dependency or canonical store.
- Floot is an operator/product manifestation and MUST consume the same semantics rather than inventing a parallel data model.
- TheHub may consume validated Skywatcher products under federation contracts.

## Certification gates

Production promotion requires all of the following for each admitted source family:

1. frozen retrieval/query provenance and source identity;
2. explicit source authority and redistribution state;
3. explicit semantic state;
4. canonical UTC handling with original time retained;
5. spatial footprint, CRS/resolution, and geometry/raster metadata where applicable;
6. gap/staleness semantics;
7. positive and negative regression tests;
8. no silent interpolation;
9. deterministic source/member accounting;
10. interactive GIS manifestation when the product is spatial;
11. zero unresolved in-scope certification residue.
