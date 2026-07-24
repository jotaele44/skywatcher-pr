# SATIM Detector Weights — Reviewed Constants Rationale

The root `satim_*.py` feature detectors (artifact-filter, cut-fill, linear-corridor,
patchwork, road-end, water-feature, visual-route-gap) score a candidate as a
weighted sum of named signals plus link/corroboration weights. Those weight
dicts are **hand-authored, reviewed constants** — deliberately *not* an
empirically-fit convex combination. This note records why, so a future reader
doesn't "fix" them into something they're not.

## They are magnitude weights, not a probability simplex

| Detector | Weight constant | Σ signal weights |
|---|---|---|
| `satim_artifact_filter.py` | `SIGNAL_WEIGHTS` (+ `LINK_WEIGHTS`) | ~1.30 |
| `satim_cut_fill.py` | `SIGNAL_WEIGHTS` (+ `LINK_WEIGHTS`) | ~1.60 |
| `satim_linear_corridor.py` | `SIGNAL_WEIGHTS` (+ `LINK_WEIGHTS`) | ~1.04 |
| `satim_patchwork.py` | `SIGNAL_WEIGHTS` (+ `LINK_WEIGHTS`) | ~1.31 |
| `satim_road_end.py` | `SIGNAL_WEIGHTS` (+ `LINK_WEIGHTS`) | ~1.40 |
| `satim_water_feature.py` | `SIGNAL_WEIGHTS` (+ `LINK_WEIGHTS`) | 1.00 |
| `satim_visual_route_gap.py` | `SCORE_WEIGHTS` | 1.00 |

Five of seven intentionally sum to **more than 1.0**. Each detector's scoring
function computes `round(clamp01(total), 4)` — the weighted sum is **clamped to
[0, 1]**, so over-summing simply means "enough strong signals saturate the
score." A naive "weights must sum to 1.0" assertion would be **wrong** for this
design and is deliberately not enforced (`tests/test_satim_detector_weights.py`
checks the properties that *do* hold: each weight is in `(0, 1]`).

## Confidence bands are standardized

All detectors band a clamped score as **HIGH ≥ 0.70 / MEDIUM ≥ 0.40 / LOW**
(see `satim_water_feature.py`, aligned in this branch — previously 0.75/0.45).
`satim_visual_route_gap.py` uses geometry-compatibility bands (≥0.70 / ≥0.40)
consistent with the family.

## Status: frozen pending a fit routine

There is currently **no fit routine for the detector family** (only the label
engine has one, `satim_fit.py`). Until labeled per-detector ground truth exists,
these weights stay frozen as reviewed constants. Changing any weight is a
deliberate review action, not a tuning knob — record the rationale here when you
do. See `docs/SATIM_PROTOCOL_TUNING.md` for the broader calibration roadmap.
