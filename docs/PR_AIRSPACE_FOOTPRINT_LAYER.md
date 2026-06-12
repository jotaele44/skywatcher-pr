# Puerto Rico Airspace Footprint Layer

## Purpose

This layer converts publicly available Puerto Rico airport tenant, hangar, FBO, cargo, government aviation, MRO, flight-school, weather-office, and helipad information into a normalized SkyWatcher reference registry.

It is a static reference layer. It is not an event feed and does not make anomaly claims.

## Inputs

- `data/reference/puerto_rico_airfields_dataset.csv`

## Outputs

- `registry/puerto_rico_airspace_footprints.csv`
- `registry/puerto_rico_helipads.csv`
- `reports/pr_airspace_footprint_import.md`

## Import Command

```bash
python scripts/import_pr_airspace_footprints.py \
  --input data/reference/puerto_rico_airfields_dataset.csv \
  --footprints-out registry/puerto_rico_airspace_footprints.csv \
  --helipads-out registry/puerto_rico_helipads.csv \
  --report reports/pr_airspace_footprint_import.md
```

## Geometry Rules

- `G0`: airport or facility known, but exact point/polygon missing.
- `G1`: point geometry known.
- `G2`: polygon geometry known.

The importer does not fabricate coordinates. It only extracts coordinates embedded in source rows.

## Correlation Rules

`skywatcher.correlation.footprint_proximity` can compare a point against G1 footprints and helipads. G0 nodes are preserved for registry completeness but skipped in distance matching until geometry is added.

## Blind Spots

1. Public tenant lists do not prove all hangar occupancy.
2. FBO, cargo-ramp, government-compound, and MRO polygons require manual geometry work.
3. FURA / Puerto Rico Police aviation sites require second-source confirmation.
4. Helipads should be reconciled against FAA NASR/NFDC before operational use.
