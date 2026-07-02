# SATIM Phase 2 Implementation Ledger

## Active Vector

`SATIM_PHASE2_CODE_STUBS`

## Scope

Target PR: #39

Branch: `feature/satim-operationalization-phase1`

This phase adds executable stubs and contract tests for the next operational layer after Phase 1 ledgers.

## Added Components

| Component | Path | Status |
|---|---|---|
| Raster candidate extraction stub | `fr24/calibration/satim_raster_candidate_extraction.py` | Added |
| Multi-date validation stub | `fr24/calibration/satim_multidate_validation.py` | Added |
| GIS overlay scoring stub | `fr24/calibration/satim_gis_overlay.py` | Added |
| AOI fixture registry | `data/satim_fixtures/aoi_registry.yaml` | Added |
| Raster extraction tests | `tests/test_satim_phase2_raster_extraction.py` | Added |
| Multi-date validation tests | `tests/test_satim_phase2_multidate_validation.py` | Added |
| GIS overlay tests | `tests/test_satim_phase2_gis_overlay.py` | Added |
| CI workflow | `.github/workflows/satim-phase2.yml` | Added |

## Test Targets

```bash
python -m pytest \
  tests/test_satim_operationalization_phase1_contracts.py \
  tests/test_satim_phase2_raster_extraction.py \
  tests/test_satim_phase2_multidate_validation.py \
  tests/test_satim_phase2_gis_overlay.py
```

## Acceptance Gates

| Gate | Expected Result |
|---|---|
| Raster extractor | Converts precomputed detections into `satim.visual_ledger.v1` rows. |
| Raster filter | Drops short/low-signal boundaries. |
| Multi-date validator | Blocks single-still promotion. |
| Multi-date validator | Marks disappearing cross-epoch boundary as mixed-epoch artifact. |
| Multi-date validator | Marks persistent cross-epoch geometry as probable ground feature candidate. |
| GIS overlay | Normalizes spatial metrics into SATIM feature scores. |
| GIS overlay | Flags infrastructure explanation when a tile seam candidate has strong infrastructure alignment. |
| CI | Runs Phase 1 and Phase 2 SATIM contract tests on PRs touching SATIM files. |

## Non-Goals

- No OpenCV/scikit-image raster implementation yet.
- No GDAL/GeoPandas hard dependency yet.
- No provider imagery download layer yet.
- No dashboard or review UI yet.
- No `main` merge in this vector.

## Follow-On Phase 3 Candidates

1. Replace precomputed raster detections with image-derived edge extraction.
2. Add optional OpenCV/scikit-image backend.
3. Add optional GeoPandas/Shapely spatial join backend.
4. Add provider metadata loader for imagery epochs.
5. Add real AOI image fixtures and golden expected outputs.
