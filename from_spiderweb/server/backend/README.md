# PRIIS Backend

This directory contains the backend API for the Puerto Rico Integrated Intelligence System (PRIIS) prototype.

## Running Locally

The backend uses [FastAPI](https://fastapi.tiangolo.com/) and can be run with
[Uvicorn](https://www.uvicorn.org/). Install the Python dependencies then
start the server:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

The API will be available at `http://127.0.0.1:8000/` and the automatic
OpenAPI documentation can be viewed at `http://127.0.0.1:8000/docs`.

## Docker

To build and run the backend in a container:

```bash
docker build -t priis-backend .
docker run -p 8000:8000 priis-backend
```

## Connecting to a Database

The backend currently uses in-memory mock data. To connect to a real
PostgreSQL/PostGIS database:

1. Define SQLAlchemy models reflecting the schemas in `../database/schema.sql`.
2. Add a `database.py` that creates an engine using a connection string from an environment variable (e.g., `DATABASE_URL`).
3. Replace the mock lists in `main.py` with queries using SQLAlchemy ORM or raw SQL.

See the `../database/README.md` for more details on setting up the database.