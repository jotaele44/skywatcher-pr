# SATIM Airport Alignment Enrichment

## Purpose

This layer integrates the Puerto Rico airport footprint registries into SATIM synthetic-boundary classification without introducing hard infrastructure rejection.

The enrichment computes:

```text
airport_alignment = 0.0 ... 1.0
```

and appends it to candidate CSV rows before L5 classification.

## Inputs

Default registries:

```text
registry/puerto_rico_airspace_footprints.csv
registry/puerto_rico_helipads.csv
```

Candidate CSV columns should include:

```text
candidate_latitude
candidate_longitude
```

Optional:

```text
airport_angle_similarity
```

## Output columns

```text
airport_alignment
nearest_airport_footprint_id
nearest_airport_facility_name
nearest_airport_facility_type
nearest_airport_footprint_distance_m
airport_footprint_match_count
```

## CLI

```bash
python -m fr24.calibration.enrich_satim_airport_alignment \
  --candidates-csv data/fr24/satim_candidates.csv \
  --output-csv data/fr24/satim_candidates.airport_enriched.csv \
  --footprint-registry registry/puerto_rico_airspace_footprints.csv \
  --footprint-registry registry/puerto_rico_helipads.csv
```

Then classify:

```bash
python -m fr24.calibration.l5_synthetic_boundary_classifier \
  --candidates-csv data/fr24/satim_candidates.airport_enriched.csv \
  --output reports/fr24/satim_l5_synthetic_boundary.json
```

## Design constraint

Airport alignment is not a rejection rule. It is passed to the L2 infrastructure feature engine and becomes part of the weighted infrastructure penalty. This prevents false negatives near airport aprons, hangars, helipads, cargo ramps, and military compounds.
