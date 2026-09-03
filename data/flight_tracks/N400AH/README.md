# N400AH structured flight-track ingestion

Dataset ID: `N400AH_STRUCTURED_TRACKS_2026Q2_Q3_v1`

- 25 original CSV/KML export pairs; 12,455 normalized observations.
- Original source files are represented by SHA-256 in `source_manifest.json`; derivatives preserve original `track_id`.
- Analytical segments split at observed gaps greater than 300 seconds. No interpolation is performed across gaps.
- Cross-export continuity edges require both a non-negative time gap of at most 60 seconds and endpoint separation of at most 1 km. Edges retain original export lineage and do not authorize interpolation.
- Speed, altitude, vertical-rate, duplicate-time, duplicate-position, and large-gap indicators are classified as data-quality flags only.
- `existing_feature_intersections.csv` compares points against the point-radius infrastructure definitions present in `src/skywatcher/corrim/gis_intelligence.py` at base commit `7dccd6c9a7e506a33aceae9c3e88466fdff47b35`. Results indicate spatial presence only.
- The existing `configs/corridor_registry.yaml` is predominantly semantic/POI-chain based and marked `auto_from_poi_chains_needs_review`; no unsupported geometric corridor intersection is asserted here.
- The August 3 track is retained as a separate geographic/time observation and is not joined to April tracks.

Generated counts:
- analytical segments: 50
- candidate continuity edges: 3
- existing-feature intersections: 95
