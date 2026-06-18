# SATIM Visual-Analysis Calibration

SATIM ("satellite/screenshot imagery") calibration sets tune how Skywatcher's
visual review treats marked features in FlightRadar24 screenshot sequences. The
engine turns human-marked labels plus per-class rules into **adjusted scores**
and **conservative promotion decisions** for a human reviewer.

## Posture

This is a public-interest transparency / research aid. It is deliberately
**conservative**:

- It *suppresses* likely false positives (palms, shadows, water, FR24 3D-render
  artifacts) rather than asserting detections.
- A feature is never "confirmed" automatically. Promotion past review requires
  the registry's cross-source / repeatability checks
  (`required_cross_source_validation`), performed by a person.
- Outputs are **scores and review flags**, not claims about ground sites. No
  image pixels are processed — only the marked labels and the rule files.

## Data layout

```
data/satim_calibration/<set>/
  README.md                     # human notes
  registry_entry.yaml           # set metadata (id, aircraft, evidence tier, scope)
  marker_legend.yaml            # marker_type -> meaning / SATIM role
  false_positive_classes.yaml   # class definitions, scoring_adjustments, promotion_thresholds
  labels.csv                    # one row per marked feature
```

Reference schema: `schemas/satim_calibration_set.schema.json` (documentation
only; validation is stdlib, see below).

## Scoring & promotion

For each label: `adjusted = clamp01(raw_confidence + scoring_adjustment[fp_class])`.
The adjustment is **0** for any `false_positive_class` that isn't one of the
canonical classes (`PALM`, `SHADOW`, `WATER`, `FR24_3D_RENDER`); such rows are
flagged `unknown_false_positive_class` and reported as a warning.

Promotion bands come from `promotion_thresholds`:

| Band | Default | Meaning |
|---|---|---|
| `candidate` | adjusted ≥ 0.80 | top review priority (still needs cross-source) |
| `cross_source_required` | ≥ 0.70 | requires independent imagery before promotion |
| `review` | ≥ 0.55 | enters human review |
| `suppressed` | < 0.55 | below review threshold |

## Commands

```bash
# Integrity check (errors fail; non-canonical classes are warnings)
python scripts/validate_satim_calibration.py data/satim_calibration

# Score a set -> exports/satim_calibration/<id>/{scored_labels.csv,summary.json}
# and (optionally) a static asset for the frontend view
python scripts/satim_score_labels.py data/satim_calibration/moca_fr24_2025 \
  --frontend-out frontend/public/satim/moca_fr24_2025.summary.json

python -m pytest tests/test_satim_calibration.py -q
```

Library entry point: `satim_calibration.py` (`load_calibration_set`,
`load_all_calibration_sets`, `score_label`, `promotion_decision`,
`score_calibration_set`). YAML parsing reuses
`pipeline.normalize_locations.load_simple_yaml` (stdlib-only; no PyYAML).

## Frontend

The vendored React app (`frontend/`) renders a read-only **SATIM Calibration**
page (`/calibration`) from the committed static summary
(`frontend/public/satim/<set>.summary.json`). It is decoupled from the
federation `/api` client, so it works with no backend.

## Known data note

The seed set `moca_fr24_2025` includes `labels.csv` rows whose
`false_positive_class` is non-canonical (`SHADOW_OR_COMPRESSION`, `TREE_CROWN`,
`COMPRESSION_OR_CANOPY`). These receive no scoring adjustment and are surfaced as
warnings for a human to reconcile — the engine does not silently rewrite the
annotations.
