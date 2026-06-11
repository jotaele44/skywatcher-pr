# PRIIS V1.5 Runbook

This runbook outlines how to set up, run, and develop against the
PRIIS V1.5 local full-stack prototype. The system consists of a
frontend (React/TypeScript), a backend API (FastAPI), a PostGIS
database, a simple data-ingestion pipeline, and stubs for a
retrieval‑augmented generation (RAG) layer.

## Prerequisites

- **Node.js** (version 18 or higher)
- **Python 3.11**
- **PostgreSQL** with the PostGIS extension (version 13 or higher)
- **Docker** (optional but recommended for containerization)

## Clone and Explore

Clone or unpack the `priis_v1_5_fullstack` project directory. The
top-level structure is:

- `frontend/` – React/TypeScript workbench using Vite and MapLibre
- `backend/` – FastAPI service exposing API endpoints
- `database/` – SQL schema and seed data for PostGIS
- `ingestion/` – Scripts for loading CSV/JSON data into the DB
- `rag/` – Stubs for the retrieval layer
- `contracts/` – JSON schemas defining entity contracts and ontology
- `docs/` – This runbook and other operational documentation

## Database Setup

1. Create a database named `priis` and enable PostGIS:

   ```bash
   createdb priis
   psql -d priis -c "CREATE EXTENSION IF NOT EXISTS postgis;"
   ```

2. Apply the schema:

   ```bash
   psql -d priis -f database/schema.sql
   ```

3. (Optional) Seed with sample data:

   ```bash
   psql -d priis -f database/seed_data.sql
   ```

4. Set the database URL in your environment:

   ```bash
   export DATABASE_URL=postgresql://<user>:<password>@localhost:5432/priis
   ```

## Backend Setup

1. Navigate to the backend directory and create a virtual environment:

   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Start the FastAPI service in development mode:

   ```bash
   uvicorn main:app --reload
   ```

   The API will be served at `http://localhost:8000/`. You can view
   interactive API docs at `http://localhost:8000/docs`.

3. To containerize the backend, run:

   ```bash
   docker build -t priis-backend backend
   docker run -p 8000:8000 --env DATABASE_URL=$DATABASE_URL priis-backend
   ```

## Frontend Setup

1. Navigate to the frontend directory:

   ```bash
   cd frontend
   npm install
   ```

2. Start the development server:

   ```bash
   npm run dev
   ```

   The workbench will be available at `http://localhost:5173/`. The
   development server proxies API requests to the backend if
   configured; otherwise adjust fetch URLs as needed.

## Data Ingestion

1. Prepare a CSV file with contract records in the format described in
   `ingestion/README.md`.
2. Run the ingestion script, passing the CSV path and database URL:

   ```bash
   python ingestion/ingest_data.py data/contracts.csv --db $DATABASE_URL
   ```

   Extend this script to handle other entities as you collect more
   datasets.

## Retrieval Layer

The `rag/` directory contains stub functions for keyword, vector,
geospatial, and graph searches. Implement these functions by
connecting to your vector store (e.g., pgvector or Qdrant) and
leveraging PostGIS for spatial queries. Once retrieval is complete,
feed the results into your LLM orchestrator.

## Local Development Tips

- Use `npm run typecheck` in the frontend to enforce TypeScript
  correctness.
- Use `uvicorn main:app --reload` to auto‑reload backend changes.
- Keep environment variables in a `.env` file (not committed) and
  load them in both backend and ingestion scripts.
- Consider using Docker Compose to orchestrate the frontend, backend,
  and database together.