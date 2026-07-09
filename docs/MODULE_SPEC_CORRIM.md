# Module Spec: CORRIM

## Role

Correlation scoring and evidence fusion only. CORRIM is the *only* module
permitted to combine SATIM's (terrain/imagery) and FPIM's (flight-path/
behavior/POI) outputs. It imports Core, SATIM, and FPIM.

## In scope

| Path | Responsibility |
|---|---|
| `src/skywatcher/corrim/gis_intelligence.py` | Puerto Rico infrastructure graph, corridor analysis, heatmap generation, anomaly detection. |
| `src/skywatcher/corrim/ilap_airspace_bridge.py` | Exports POI/corridor candidates as GeoJSON for ILAP/Spiderweb, scored against infrastructure alignment. |
| `src/skywatcher/corrim/aasb_airspace_bridge.py` | Airport-node edge export for AASB/UGCN integration. |
| `src/skywatcher/fusion/anomaly_scoring.py` | Scores current vs. historical baselines; explicitly `operator_action: review_context_only`, `live_tracking: False`, `operational_cueing: False`. |
| `src/skywatcher/fusion/historical_baselines.py` | Historical baseline data for anomaly scoring. |
| `src/skywatcher/fusion/cross_domain_overlap.py` | Finds overlaps across data domains. |
| `src/skywatcher/fusion/coastal_corridor_index.py` | Coastal corridor indexing for correlation. |

## Out of scope

- Classifying imagery/terrain content directly (SATIM).
- Extracting or vectorizing flight tracks directly (FPIM).
- **POI/footprint gazetteer matching** (`correlate_point_to_footprints`) —
  this lives in FPIM (`src/skywatcher/correlation/footprint_proximity.py`);
  CORRIM consumes its output (a POI-proximity list), it does not compute it.
- Intent/purpose inference of any kind.

## Backward compatibility

`gis_intelligence.py`, `ilap_airspace_bridge.py`, and `aasb_airspace_bridge.py`
at their original root paths are thin re-export shims over the modules
above. `ilap_airspace_bridge.py`'s internal dependency on
`gis_intelligence.PuertoRicoInfrastructure`/`haversine_nm` was repointed to
the new `skywatcher.corrim.gis_intelligence` location; its own public
surface (`ILAPAirspaceBridge`, `CONFIDENCE_WEIGHTS`, etc.) is unchanged.
