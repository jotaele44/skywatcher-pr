# SATIM-CAL-CONTROL-MOCA_v1

Control / anchor calibration set for Skywatcher-PR SATIM review.

## Purpose

The primary `moca_fr24_2025` set is built entirely from *ambiguous* marks on T2
Flightradar24 screenshots. A calibration corpus made only of ambiguous cases is
unbalanced: there is nothing the engine can use as confirmed ground truth.

This control set anchors the corpus with features whose identity is **known** from
orthorectified reference imagery:

- confirmed-positive false-positive exemplars (a real palm crown, a real
  pool/cistern, a confirmed FR24 3D-render tile seam) that *should* be suppressed,
- a confirmed-negative feature (a genuine ground structure) that should *not* be
  suppressed.

The per-feature true-positive / false-positive verdicts live in `ground_truth.csv`
and feed the empirical fitter (`scripts/fit_satim_calibration.py`) alongside the
cross-source and review-harvested labels.

## Evidence tier

- Tier: T1 orthorectified reference (Esri / USGS basis), not T2 screenshot.
- Use as fixed ground truth, not for visual marker calibration.

## Status

Registered as a `control` set in `../registry.yaml`. It is never the `active`
scoring set, so it does not affect production export scoring.
