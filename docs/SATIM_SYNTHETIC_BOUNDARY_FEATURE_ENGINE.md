# SATIM Synthetic Boundary Feature Engine

## Purpose

This layer separates feature generation from classification so tile-seam detection does not become a brittle set of infrastructure rejection rules.

The pipeline is:

```text
L0 -> candidate extraction
L1 -> radiometric evidence
L2 -> infrastructure alignment scoring
L3 -> terrain continuity
L4 -> landcover/coastal persistence
L5 -> synthetic boundary classifier
```

## Feature modules

```text
fr24/calibration/features/boundary_geometry.py
fr24/calibration/features/radiometric_features.py
fr24/calibration/features/infrastructure_features.py
fr24/calibration/features/terrain_features.py
fr24/calibration/features/landcover_features.py
fr24/calibration/l5_synthetic_boundary_classifier.py
```

## Design rule

Infrastructure is scored, not rejected.

Avoid:

```python
if road_overlap:
    reject
```

Use:

```python
road_alignment = 0.0 ... 1.0
building_alignment = 0.0 ... 1.0
airport_alignment = 0.0 ... 1.0
parcel_alignment = 0.0 ... 1.0
```

The L5 classifier applies a weighted infrastructure penalty. This keeps airport, industrial, port, and urban candidates auditable instead of deleting them early.

## Current L5 weights

```yaml
straightness: 0.20
radiometric_delta: 0.30
terrain_crossing: 0.15
landcover_persistence: 0.20
infrastructure_rejection: 0.10
orthogonality: 0.05
coastal_crossing_score: 0.05
```

Orthogonality is intentionally weak because Puerto Rico has many real 90-degree structures: roads, hangars, aprons, container yards, parking lots, parcels, and urban grids.

## Airport footprint integration

`infrastructure_features.py` includes loader and scoring helpers for airport footprint registries:

```text
registry/puerto_rico_airspace_footprints.csv
registry/puerto_rico_helipads.csv
```

When those registries are geocoded, the geospatial layer should compute candidate overlap and angle similarity, then pass the result as:

```text
airport_alignment
```

This should remain an alignment score, not a hard rejection.

## PR-specific coastal feature

`coastal_crossing_score` supports Puerto Rico seam detection where candidate discontinuities continue across:

```text
land -> beach -> reef -> water
```

This is useful around Aguadilla, Isabela, Cabo Rojo, Vieques, Culebra, Ceiba, and Fajardo.

## Classifier output

```json
{
  "classification": "probable_tile_seam",
  "confidence": 0.91,
  "tile_seam_likelihood": 0.91,
  "persistent_ground_feature_likelihood": 0.10,
  "cloud_shadow_likelihood": 0.00,
  "terrain_shadow_likelihood": 0.00
}
```

## Validation

Run:

```bash
python -m pytest tests/test_satim_synthetic_boundary_features.py tests/test_l5_synthetic_boundary_classifier.py
```
