# PRIIS Server

FastAPI orchestration layer for the Puerto Rico Integrated Intelligence System.

## Quick start

```bash
# From the repo root

# 1. Install dependencies
pip3 install -r server/backend/requirements.txt

# 2. Initialise the database and seed demo data
sqlite3 server/priis.db < server/database/schema_sqlite.sql
python3 server/ingestion/seed_demo.py

# 3. Start the API server
python3 -m uvicorn server.backend.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs`

## API reference

### Entity endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Server health + DB status |
| GET | `/agencies` | All agencies |
| GET | `/vendors` | All vendors with risk score |
| GET | `/sites` | All sites with coordinates |
| GET | `/contracts` | All contracts |
| GET | `/events` | All timeline events |
| GET | `/anomalies` | All anomalies with factors |
| GET | `/sources` | All data sources with health |
| GET | `/investigations` | All investigations |
| GET | `/alerts` | Recent alert queue |

### Pipeline (Flight Log Processor)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/pipeline/run` | Start `run_all.py`; returns `job_id` |
| GET | `/pipeline/status/{job_id}` | Job status |
| GET | `/pipeline/events/{job_id}` | SSE stream of stdout |
| DELETE | `/pipeline/{job_id}` | Terminate job |

Request body for `/pipeline/run`:
```json
{ "phase": 0, "images": 100 }
```
Both fields are optional. Omit `phase` to run all phases.

### GeoJSON layers

| Method | Path | Description |
|--------|------|-------------|
| GET | `/geo/flights.geojson` | Flight path FeatureCollection |
| GET | `/geo/sites.geojson` | Site point FeatureCollection |
| GET | `/geo/anomalies.geojson` | Anomaly point FeatureCollection |
| GET | `/geo/corridors.geojson` | Corridor polygon FeatureCollection |

GeoJSON files are read from `outputs/` after a pipeline run. Returns an empty
FeatureCollection when the file hasn't been generated yet.

### RAG / Query

| Method | Path | Description |
|--------|------|-------------|
| POST | `/rag/query` | SSE stream of `query_llm.py` output |
| POST | `/rag/index` | Trigger `rag_pipeline.py` (re-index) |

Request body for `/rag/query`:
```json
{ "query": "vendors near sensitive sites", "top_k": 5, "no_context": false }
```

## Ingesting real pipeline outputs

After running `run_all.py`, the ingestion script maps CLI outputs into the
SQLite database:

```bash
python3 server/ingestion/ingest_data.py
```

This maps:
- FR24 Parquet/CSV → `contracts` + `events` tables
- `gis_intelligence.py` GeoJSON → `sites` table
- `earthgpt/` anomaly JSON → `anomalies` table
- Demo financial CSVs → `contracts` + `vendors` tables

## Directory structure

```
server/
├── backend/
│   ├── main.py              # FastAPI app (CORS, SQLite, SSE, GeoJSON, RAG)
│   └── requirements.txt     # fastapi, uvicorn, sse-starlette, aiosqlite, pydantic
├── database/
│   ├── schema_sqlite.sql    # SQLite schema (matches priis.ts types)
│   └── schema.sql           # Original PostgreSQL schema (reference only)
├── ingestion/
│   ├── seed_demo.py         # Seeds DB with V1 demo data
│   └── ingest_data.py       # Maps real pipeline outputs to DB
├── rag/
│   └── retrieval.py         # Hybrid retrieval stubs (keyword/vector/geo/graph)
├── priis.db                 # SQLite database (created by seed_demo.py)
└── README.md
```
