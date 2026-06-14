# Skywatcher-PR Dashboard

Local-only React dashboard for the Skywatcher airspace-intelligence module.
Built with the federation's shared frontend process — Vite + React (JSX) +
Tailwind + shadcn/ui + react-query — with the Base44 auth layer stripped. It
talks only to the repo's FastAPI backend; **MapLibre GL** renders the map.

## Run

```bash
# 1. Backend (from from_spiderweb/) — seed the SQLite DB first, then serve on :8000
cd ../from_spiderweb
python server/ingestion/seed_demo.py          # creates server/priis.db (+ synthetic flight tracks)
uvicorn server.backend.main:app --reload --port 8000

# 2. Frontend (this dir) on :5173
npm install
npm run dev
```

Open http://localhost:5173. Point at a different API with
`VITE_API_BASE=http://host:port npm run dev` (default `http://localhost:8000`).

## What it shows
- **Map** (MapLibre) — infrastructure sites + anomaly halos, built client-side
  from `/sites` + `/anomalies` (no `/geo/*` files required). Flight-track replay
  draws the selected event's ADS-B polyline with a scrubber.
- **Events** — mixed event log (flight / contract / imagery / report / outage),
  polled every 15s; click a flight to replay its track.
- **Anomalies** — cards by severity band; detail sheet with factors / linked
  contracts / events / contradictions.
- **Alerts / Sources** — watchlist feed and live source-health strip.
- **Tools** — pipeline + RAG panels that degrade gracefully when those backend
  scripts aren't installed.

## Backend
Reuses the existing FastAPI at `../from_spiderweb/server/backend/main.py`
(CORS already allows `:5173`). API fields are **camelCase**
(`siteId`, `altitudeFt`, `flightStatus`, …).
