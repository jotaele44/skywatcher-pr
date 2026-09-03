# FR24 Image Analysis Skill — Fixture Validation v0.2

## Fixture

Operator-local file: `IMG_0218 (Merged)(1).pdf`

The source PDF was not committed. Validation used the uploaded local copy after preserving the original SHA-256 in the generated package.

## Runtime

- PDF renderer: `pdftoppm`
- Render resolution: 72 DPI for deterministic validation throughput
- OCR: typed Pillow + `pytesseract` regional adapter
- UI segmentation: repository `FR24UISegmenter` when importable; deterministic geometric fallback otherwise
- Route extraction: repository `fr24.track_vectorizer` when importable; conservative green-route mask fallback otherwise
- SATIM candidate pass: map-region gradient seam detector plus unresolved dark-surface screening

## Results

| Gate | Result |
|---|---:|
| PDF pages expected | 39 |
| PDF pages rendered | 39 |
| Source accounting | 100% |
| Frame hash coverage | 39/39 (100%) |
| OCR ledger rows | 76 |
| SATIM artifact ledger rows | 75 |
| Repeat-view rows | 39 |
| Deterministic run ID | PASS |
| Normalized deterministic digest rerun | PASS |
| Stage 1 freeze before Stage 2 | PASS |
| Both stages frozen before correlation | PASS |
| Fixed-bounds promotion | Disabled |
| Facility-purpose inference | Disabled |
| Flight-intent inference | Disabled |

Run ID: `SWFR24-63DDE1A059AFCD48`

Normalized deterministic digest: `5db046bc794ca409afb2130ad49357ce19cb83a0f51066f32b7679c158bc607a`

## Screen-derived candidates

The OCR adapter recovered the following candidates from the fixture:

- Registration: `N6654G`
- Altitude example: `2,960 ft`
- Groundspeed example: `118 mph`
- Replay timezone: `UTC-04:00`

All remain `screen_derived_unverified`. Device-capture time and FR24 replay time remain separate fields.

## Registration status

The registered track output remains explicitly `not_registered` because this fixture run did not produce a validated multi-anchor affine solution. No fixed Puerto Rico bounds or synthetic coordinates were used.

## SATIM status

The SATIM pass generates candidate-only findings. `POSSIBLE_TILE_SEAM` requires repeat-view or external-source corroboration. `DARK_SURFACE_POLYGON` remains unresolved because screenshot-only evidence cannot distinguish shadow, water, terrain, or mosaic differences reliably.

## Local test status

A local deterministic smoke test using a valid generated PNG passed. The full repository suite could not be executed because the available runtime could not clone GitHub over the network. CI remains authoritative for repository-wide compatibility.

## Known limitations

1. OCR is selectively applied to high-value and sampled pages rather than every region on every page.
2. Video support remains inherited from v0.1 and was not fixture-tested here.
3. Affine georegistration remains gated pending matched control points.
4. The seam detector is conservative and produces review candidates, not certified artifacts.
5. Existing repository SATIM calibration layers remain authoritative when their complete input contracts are supplied.
