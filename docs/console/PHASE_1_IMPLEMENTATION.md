# Interactive Airspace Console — Phase 1 Implementation

## Scope

Phase 1 implements contracts and capability reporting only. It does not implement the interactive map, normalized operational ingestion, playback UI, or airport operational adapters.

## Added

- Seven JSON Schemas.
- Additive source taxonomy and machine-readable mapping.
- UTC-only datetime validation.
- Opaque cursor encoding with integrity and filter binding.
- Reversible SQLite migration version 1.
- `/api/console/capabilities`.
- Explicit 24-of-24 capability coverage.
- Schema, mapper, UTC, cursor, migration, endpoint, and regression tests.

## Preserved

- Existing React pages.
- `PuertoRicoMapShell` SVG diagnostic map.
- Static Leaflet report generator.
- Desktop wrapper.
- Generic `/api/entities/*` API.
- FR24 screenshot-processing and evidence modules.

## Policy enforcement

- No FlightRadar24 endpoint scraping.
- No proprietary visual assets.
- Screenshot data remains evidence-only.
- Synthetic records are not production eligible.
- Unknown source types remain explicit and receive a QA flag.
- Console persistence tables require provenance columns.
- Datetimes must include a timezone and normalize to UTC.

## Local validation

```text
python -m compileall -q server scripts tests
python -m pytest -q
19 passed
```

Complete-repository regression testing is delegated to GitHub Actions because the execution runtime could not clone GitHub directly. The draft PR must remain unmerged until CI completes successfully.
