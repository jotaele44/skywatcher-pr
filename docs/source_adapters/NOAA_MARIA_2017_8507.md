# NOAA Hurricane Maria 2017 (Digital Coast dataset 8507)

This adapter is the first live-provider implementation of the Skywatcher certified acquisition contract mirrored from Spiderweb's generic source-adapter substrate.

## Frozen public denominator

- Dataset: **2017 NOAA NGS DSS Natural Color 8 Bit Imagery: Hurricane Maria**
- Digital Coast dataset id: **8507**
- Published bulk size: **193G**
- Published approximate GSD: **25 cm**
- Public URL-list lines: **1187**
- TIFF assets: **590**
- Per-item STAC JSON records: **590**
- Other catalog/metadata entries: **7** (6 before TIFFs + STAC index)
- Arithmetic: **6 + 590 + 1 + 590 = 1187**

The adapter requires the 590 TIFF ids and 590 per-item STAC ids to close one-to-one before any raw-image fetch plan is accepted.

## Temporal contradiction firewall

The public STAC item for pilot id `20170924bC0660430w183000n` carries a filename-encoded date candidate of 2017-09-24 while its STAC `properties.datetime` is 2017-09-22T00:00:00Z. The adapter preserves both observations and emits `CONTRADICTION_TIME`; it does not silently choose a date. When this occurs, the fetch endpoint's `imagery_epoch` remains `UNKNOWN` pending adjudication.

## Lineage semantics

All derived crops/patches from an item inherit a conservative batch lineage derived from the filename acquisition batch, for example `NOAA_MARIA_2017_8507::20170924b`. This is intentionally coarser than tile identity to reduce train/validation/test leakage across the same acquisition batch. It is not asserted as authoritative flight-line identity.

## Commands

```bash
python -m scripts.source_adapters.noaa_maria_2017.cli discover --output-root /tmp/noaa-maria-8507
python -m scripts.source_adapters.noaa_maria_2017.cli dry-run --output-root /tmp/noaa-maria-8507
python -m scripts.source_adapters.noaa_maria_2017.cli fetch-pilot --output-root /tmp/noaa-maria-8507
```

`discover` fetches metadata/catalog documents only. `dry-run` constructs certified payload requests but does not fetch image bytes. `fetch-pilot` uses the shared staged/hash/cache/receipt engine.

## Rights posture

Catalog access does not establish calibration-training or redistribution rights. Current policy is:

- fetch: ALLOWED
- training: ALLOWED
- redistribution: ALLOWED

Rights binding uses NOAA InPort item 52283 (Access Constraints: None) plus the federal Data.gov dataset record, which publishes CC0-1.0. The raw STAC license code `NLPL` is retained as a conflicting/source-specific observation rather than overwritten.

## GSD contradiction

The NOAA storm viewer describes the approximate GSD as ~25 cm, while NOAA InPort supplemental metadata states 15 cm. Both are preserved as source observations and the canonical GSD remains unresolved until the product-level metadata/processing lineage is adjudicated.
