# Skywatcher Spatial Responsibility v1

Status: PROVISIONAL / NON-CERTIFYING

Skywatcher remains authoritative for aviation, airspace, trajectories, imagery-forensic algorithms, terrain/bathymetric analytics, and aviation-specific spatial reasoning.

It may remain internally GDAL-light for bounded workloads. Federation spatial services are consumed for heterogeneous authoritative geometry, reusable topology, CRS handling, and canonical boundaries when that improves correctness or scale.

## Retained ownership
- 4D flight-track and corridor semantics
- restricted-airspace event semantics
- imagery/change-detection logic
- terrain/bathymetric derivative algorithms
- aviation evidence interpretation

## Delegable spatial primitives
- geometry validation/canonicalization
- CRS transformation
- topology predicates
- canonical boundaries/coastline
- heterogeneous vector ingestion support

## Non-equivalence safeguard
A spatial intersection does not establish aircraft intent, infrastructure causation, or event identity. Proximity remains discovery unless independently supported.

## Migration gate
No existing trajectory/imagery/terrain output is replaced until source/retained/excluded arithmetic, CRS, geometry delta, stable-ID, duplicate, null, cardinality, and positive/negative regression tests pass against the retained baseline.
