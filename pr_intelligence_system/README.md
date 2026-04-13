# PR Intelligence System

A production-grade geospatial intelligence system that performs multi-format
data ingestion, CRS normalisation, physics-based feature extraction, anomaly
attribution, temporal persistence tracking, and spatial clustering to produce
a ranked anomaly output.

---

## Repository Structure

```
pr_intelligence_system/
├── core/
│   ├── ingest/
│   │   ├── loaders/
│   │   │   ├── csv_loader.py
│   │   │   ├── vector_loader.py
│   │   │   ├── raster_loader.py
│   │   │   └── archive_extractor.py
│   │   ├── detect.py
│   │   ├── dispatcher.py
│   │   ├── unify.py
│   │   ├── registry.py
│   │   ├── crs.py
│   │   ├── raster_features.py
│   │   └── grid_align.py
│   ├── preprocessing/
│   │   └── normalize_coords.py
│   ├── graph/
│   │   └── build_corridor_graph.py
│   ├── validation/
│   │   └── validate_corridors.py
│   ├── physics/
│   │   ├── terrain_bathy_engine.py
│   │   ├── slope.py
│   │   ├── hydrology.py
│   │   └── constraint_engine.py
│   ├── attribution/
│   │   ├── anomaly_attribution.py
│   │   └── advanced_attribution.py
│   ├── masking/
│   │   └── infrastructure_overlay.py
│   ├── temporal/
│   │   └── persistence_engine.py
│   └── clustering/
│       └── spatial_cluster.py
├── scripts/
│   ├── run_real_ingestion.py
│   ├── run_physics_constraints.py
│   ├── run_full_pipeline.py
│   ├── run_anomaly_attribution.py
│   ├── run_snapshot.py
│   └── run_temporal_clustering.py
├── data/
│   ├── raw/            ← place input files here
│   ├── output/
│   │   └── snapshots/
│   └── grid/
├── config/
├── utils/
├── run_all.py
├── requirements.txt
└── README.md
```

---

## Environment Setup

### 1. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate        # Linux / macOS
# .venv\Scripts\activate.bat     # Windows
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `geopandas` and `rasterio` have native C dependencies.
> On Linux install system packages first:
> ```bash
> sudo apt-get install -y libgdal-dev gdal-bin libproj-dev libgeos-dev
> ```
> On macOS:
> ```bash
> brew install gdal proj geos
> ```

---

## Data Ingestion

Place any of the following file types into `data/raw/` before running:

| Format  | Extensions           |
|---------|----------------------|
| CSV     | `.csv`               |
| Vector  | `.shp` `.gpkg` `.geojson` `.kml` |
| Raster  | `.tif` `.tiff`       |
| Archive | `.zip` `.tar` `.gz`  |

Archives are extracted recursively and their contents dispatched
to the appropriate loader.

If `data/raw/` is **empty**, the pipeline automatically generates 500
synthetic geospatial demonstration points and runs the full pipeline on
those.

---

## Execution

Run the complete pipeline from the project root:

```bash
cd pr_intelligence_system
python run_all.py
```

Individual steps can also be run standalone:

```bash
python scripts/run_real_ingestion.py
python scripts/run_physics_constraints.py
python scripts/run_full_pipeline.py
python scripts/run_anomaly_attribution.py
python scripts/run_snapshot.py
python scripts/run_temporal_clustering.py
```

---

## Pipeline Steps

| Step | Script | Description |
|------|--------|-------------|
| 1 | `run_real_ingestion.py`      | File detection, loading, CRS normalisation, grid alignment |
| 2 | `run_physics_constraints.py` | Terrain/bathymetry, slope, hydrology, physics score |
| 3 | `run_full_pipeline.py`       | Corridor graph, validation, infrastructure masking |
| 4 | `run_anomaly_attribution.py` | Classification, confidence, LOF scoring, ranking |
| 5 | `run_snapshot.py`            | Temporal persistence, snapshot save |
| 6 | `run_temporal_clustering.py` | DBSCAN clustering, final score fusion, ranked output |

---

## Expected Outputs

| File | Description |
|------|-------------|
| `data/output/unified_features_enriched.csv` | Intermediate enriched feature set |
| `data/output/final_anomaly_ranked.csv`      | Final ranked anomaly output |
| `data/output/snapshots/snapshot_*.csv`      | Timestamped detection snapshots |

### `final_anomaly_ranked.csv` columns

| Column          | Description |
|-----------------|-------------|
| `lat`           | Latitude (EPSG:4326) |
| `lon`           | Longitude (EPSG:4326) |
| `cell_id`       | Grid cell identifier |
| `physics_score` | Combined physics constraint score [0–1] |
| `slope`         | Terrain slope magnitude |
| `hydro_align`   | Hydrological alignment score [0–1] |
| `classification`| anomaly / infrastructure / natural / noise |
| `confidence`    | Classification confidence [0–1] |
| `persistence`   | Number of times cell_id detected across snapshots |
| `cluster`       | DBSCAN cluster label (-1 = noise) |
| `final_score`   | Fused final ranking score [0–1] |
