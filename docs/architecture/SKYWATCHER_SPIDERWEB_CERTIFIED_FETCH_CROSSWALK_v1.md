# Skywatcher ↔ Spiderweb Certified Fetch Crosswalk v1

## Scope

Mirror Spiderweb's source-adapter transport/provenance substrate in Skywatcher without collapsing domain ownership.

Reference Spiderweb contract:

`source endpoint -> expected universe -> request plan -> payload download -> hash -> manifest -> coverage ledger -> optional normalization`

Skywatcher specialization:

`source registry -> product/item denominator -> rights gate -> deterministic request -> staged fetch -> SHA256/content-addressed cache -> raw manifestation -> receipt/coverage ledger -> source-lineage assignment -> derived calibration samples -> lineage-safe split -> calibration`

## INTERSECTION

Both repositories require:

- stable source/endpoint identity;
- deterministic request identity and parameters;
- runtime-only raw payloads;
- immutable SHA256 byte identity;
- small committed manifests/ledgers;
- HTML/error payload hold behavior;
- expected/requested/acquired/failed/hold accounting;
- no silent overwrite of raw evidence;
- explicit source universe/denominator;
- download success is not certification.

## SPIDERWEB_ONLY

Spiderweb remains authoritative for spatial-source semantics such as:

- GIS feature/schema/CRS validation;
- AOI/source geometry completeness;
- row/source-asset conservation;
- stable spatial IDs and geometry promotion;
- canonical GIS layer production.

Skywatcher does not inherit these semantics merely because it reuses the acquisition pattern.

## SKYWATCHER_ONLY

Skywatcher adds:

- `source_lineage_id` before any crop/patch/derivative;
- imagery provider/product/epoch metadata;
- independent `fetch`, `training`, and `redistribution` rights states;
- quality/cloud/occlusion/calibration suitability gates;
- same-scene derivative leakage prevention;
- train/validation/test source-lineage isolation;
- imagery-specific object/control corpus promotion.

Binding rules:

- `FETCHABLE != TRAINING_ELIGIBLE != REDISTRIBUTABLE`.
- `BYTE_CHANGED` proves only byte difference.
- same-source crop/screenshot/resize remains the same source lineage.
- source classification is not scene/object identity.
- download != validation != annotation != calibration != certification.

## Runtime path contract

Raw, staging, and content-addressed cache paths are runtime artifacts and must remain outside git-tracked corpus manifests. Git should retain only reproducibility metadata, schemas, receipts, hashes, coverage ledgers, and reviewable promoted outputs.

## Refresh behavior

1. Fetch to `.part` staging.
2. Hash bytes before promotion.
3. Unexpected payloads move to `hold` and never replace prior valid raw data.
4. Expected-hash mismatch moves to `hold`.
5. Content-addressed cache is keyed by SHA256.
6. Raw manifestation naming includes a digest prefix.
7. Existing prior valid manifestation is preserved after fetch/validation failure.
8. `UNCHANGED` is byte identity relative to a supplied prior hash only.
9. `BYTE_CHANGED` does not establish logical/schema/geometric change.

## Source registry posture

Catalog endpoints are not automatically payload endpoints. NOAA/USGS/Copernicus catalog/provider entries must be resolved to item/product URLs and frozen item metadata before actual acquisition. SIGE and third-party imagery exposed through viewers remain discovery/review-only while rights are unbound.

## Certification

`FETCH_CONTRACT_EQUIVALENCE = PASS_CODE_IMPLEMENTED`

`DOMAIN_CERTIFICATION_EQUIVALENCE = PROHIBITED`

A clean local/unit execution plus repository CI is still required before certified promotion. Existing repository-wide CI infrastructure failure remains a separate blocker.
