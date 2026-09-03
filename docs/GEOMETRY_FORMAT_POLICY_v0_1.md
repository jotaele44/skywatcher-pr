# Geometry Format Policy v0.1 — Skywatcher

## Boundary

Skywatcher's browser/map boundary remains GeoJSON/MapLibre-compatible. TWKB is not a frontend geometry contract.

Recommended path:

`SOURCE TRACK -> canonical XYZ/XY track -> optional TWKB backend/cache derivative -> decode -> GeoJSON -> MapLibre`

## Admission rules

TWKB is admitted only when all of the following are explicit and verified:

- frozen source track
- CRS
- XY/XYZ/XYM/XYZM dimension
- XY precision and, for XYZ/XYZM, Z precision
- round-trip success
- geometry-type conservation
- validity-state conservation
- vertex-count conservation
- application tolerance >= observed round-trip coordinate error
- independent canonical track retained

Any missing CRS or implicit precision is BLOCKED. Any validity/vertex-count change is FAIL. A passing TWKB derivative remains NONCANONICAL.

## Existing corpus note

The geometry-format benchmark found substantial size reduction for the frozen dense track corpus at precision 6, but the stored GeoJSON lacked a declared CRS. That corpus therefore remains blocked from TWKB admission until CRS is independently bound; coordinate plausibility alone is not identity evidence.
