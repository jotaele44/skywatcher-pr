# SATIM-CAL-MOCA-C6038_v1

Calibration packet for Skywatcher-PR SATIM review using the Moca / Antigua Escuela de Moca Flightradar24 3D screenshot sequence for aircraft C6038 / CG638 / H60, Sikorsky MH-60T Jayhawk.

## Purpose

This packet supports QA for screenshot-based imagery interpretation.

Calibration targets:

- Tile seam and level-of-detail boundary detection
- Smudge or low-texture vegetation blending detection
- False-positive suppression for palms, shadows, water, and Flightradar24 3D rendering
- Curved or slanted geometry checks in oblique mobile screenshots
- Ambiguous object or shadow tagging

## Evidence tier

- Tier: T2 operational screenshot
- Not T1 orthorectified source imagery
- Use for calibration and model tuning only

## Marker legend

| Marker | Meaning | SATIM use |
|---|---|---|
| dotted_line | suspected seam | tile or LOD boundary detection |
| squiggle | smudge or texture loss | texture-frequency anomaly scoring |
| triangle | body of water / pool / cistern | known feature class |
| straight_line | geometry warp or slanted edge | perspective check |
| x | palm tree | vegetation false-positive class |
| circle | unusual object or shadow | ambiguous candidate class |

## Image storage

Store source files under:

```text
data/satim_calibration/moca_fr24_2025/raw/
data/satim_calibration/moca_fr24_2025/annotated/
```

## Processing

Validate and score this set with the SATIM engine (see
`docs/SATIM_CALIBRATION.md`):

```bash
python scripts/validate_satim_calibration.py data/satim_calibration/moca_fr24_2025
python scripts/satim_score_labels.py data/satim_calibration/moca_fr24_2025
```

## Promotion rule

Promote a marked feature only after:

1. repeatability across frames,
2. cross-source persistence outside FR24,
3. geometry coherence review,
4. false-positive screening.

Registered set: `SATIM-CAL-MOCA-C6038_v1`
