# ILAP Calibration Corpus Workspace

This directory holds **manifests and adjudication metadata**, not a claim that the image corpus is complete.

## Required corpus families

- `palm_tree`
- `roof_tarp_pool_glare`
- `vehicle_baseline`
- `path_network`
- `access_friction`

## Source-state vocabulary

- `GROUND_TRUTH`: independently supported class identity appropriate to the task.
- `ANALYST_LABEL`: human annotation not yet independently bound.
- `MACHINE_LABEL`: detector output only.
- `ADJUDICATED`: analyst/machine disagreement resolved with supporting evidence.
- `UNRESOLVED`: evidence remains insufficient or tied.

## Leakage firewall

Rows sharing the same underlying imagery source, scene, capture, or derivative lineage must not be split across train/validation/test as if independent. `source_lineage_id` is mandatory before model calibration.

## Denominator rule

A corpus family is `OPEN` until all intended source strata, positive controls, negative controls, and confusion classes are enumerated and frozen. Counts must close by class and split before any certification metric is reported.
