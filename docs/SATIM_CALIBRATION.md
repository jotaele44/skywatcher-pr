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

## Class resolution (aliases)

Each label's `false_positive_class` resolves to a canonical scoring class:

- already canonical (`PALM`, `SHADOW`, `WATER`, `FR24_3D_RENDER`) → `resolved`;
- mapped through `false_positive_aliases` in `false_positive_classes.yaml`
  (e.g. `TREE_CROWN → PALM`) → `aliased`, preserving the analyst's original
  wording while applying the canonical adjustment;
- otherwise → `unknown` (no adjustment, flagged + warned).

Alias targets must themselves be canonical (validator-enforced).

## Scoring & promotion

For each label: `adjusted = clamp01(raw_confidence + scoring_adjustment[resolved_class])`.
Unknown classes get **0** adjustment. Promotion bands come from `promotion_thresholds`:

| Band | Default | Meaning |
|---|---|---|
| `candidate` | adjusted ≥ 0.80 | top review priority (still needs cross-source) |
| `cross_source_required` | ≥ 0.70 | requires independent imagery before promotion |
| `review` | ≥ 0.55 | enters human review |
| `suppressed` | < 0.55 | below review threshold |

## Promotion gate, repeatability, provenance

The scored summary also carries:

- **`promotion_gate`** — the registry's `required_cross_source_validation` sources
  plus `marker_legend` `promotion_checks`, all `status: pending`. These are the
  human gates a `candidate` must clear; the engine never marks them satisfied.
- **`repeatability`** — distinct-frame count per `feature_class`
  (`frame_to_frame_repeatability`). A **reported signal only**; it does not change
  any score.
- **`provenance`** — `engine_version` + SHA-256 of each source file, for
  reproducibility/auditability.

## Commands

```bash
# Integrity check (errors fail; unresolved classes / soft issues warn)
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

## Reference schemas

Documentation-only (validation is stdlib via `scripts/validate_satim_calibration.py`):
`schemas/satim_calibration_set.schema.json`, `schemas/satim_marker_legend.schema.json`,
`schemas/satim_false_positive_classes.schema.json`.

## Known data note

The seed set `moca_fr24_2025` has `labels.csv` rows whose `false_positive_class`
is a compound/observed value (`SHADOW_OR_COMPRESSION`, `TREE_CROWN`,
`COMPRESSION_OR_CANOPY`). These are reconciled via `false_positive_aliases`
(→ `SHADOW`, `PALM`, `SHADOW`) rather than by rewriting `labels.csv`, so the
analyst's original wording is preserved. The alias targets are conservative
defaults and are analyst-adjustable.
