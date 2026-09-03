# Craft Profiles & Query Layer

Skywatcher consolidates the FR24/RLSM corpus into a **per-craft profile** and makes
it **queryable** — in structured form or natural language — so you can ask, per
aircraft: what's its regular schedule, where is it based, which landing zones does it
prefer, what routes recur, and what's new since the last build.

> **Doctrine.** Profiles and answers describe *observed facts* only. Skywatcher
> **never infers intent, mission, or purpose** from geometry, gaps, ownership, POI
> proximity, or screenshots. Every aggregate is a review-gated **candidate** carrying
> a confidence grade, an evidence tier (T1–T4), and — for recurrence/spatial claims —
> the eligible-period denominator it was graded against. `primary_mission` is stated
> as fact only for operator-declared (`known_db`) aircraft.

## Data flow

```
RLSM SQLite (aircraft_observations, flight_track_features, labeled_pins,
             manual_flight_log, aircraft_registry, geo_anchors)
   + KNOWN_OPERATORS + configs/{airport,lz,hangar}_registry.yaml
        │  FPIM cores: fpim/schedule.py, fpim/route_recurrence.py,
        │              fpim/endpoint_matcher.py, fpim/aircraft_profile.py
        ▼
  CraftProfileBuilder (fpim/craft_profile.py)
        ├─► craft_profiles table (incremental upsert) + profile_snapshots (diff)
        └─► profiles/craft/<reg>.json (schema: schemas/craft_profile.schema.json)
        ▼
  QueryEngine (query/engine.py) ─► Answer{facts, citations, grade, gaps, caveats}
        ├─ CLI:  scripts/skywatcher_query.py
        ├─ HTTP: POST /api/query        (+ GET /api/entities/AircraftProfiles)
        └─ LLM:  query/llm.py (Anthropic; grounded-only; degrades offline)
```

## Confidence grading

Grades (`src/skywatcher/core/confidence.py`): `VERIFIED / HIGH / MODERATE / LOW /
INSUFFICIENT`, reconciled with the legacy 0–1 `confidence_level`. Coverage-gate caps:

- recurrence/cadence with **no eligible-period denominator** → capped below HIGH;
- **spatial** claims (home base / LZ) with **no georeferencing** → capped ≤ MODERATE;
- **no source/receiver context** → capped ≤ LOW.

`known_db` (operator-declared) identity can reach VERIFIED; deduced profiles are capped
at HIGH and never assert a mission.

## Build profiles

The RLSM database (`data/rlsm/rlsm_screenshot_analysis.sqlite`) is real operator data
and is gitignored — build on a workstation that has ingested it:

```bash
python scripts/build_craft_profiles.py            # all registrations
python scripts/build_craft_profiles.py --craft N5854Z
```

Re-running is incremental: it recomputes aggregates, bumps activity, and diffs against
the previous snapshot to surface `new_patterns` / `recurring_events`. Against an absent
DB it exits cleanly.

## Query

```bash
# Natural language (uses ANTHROPIC_API_KEY when set; else deterministic text):
python scripts/skywatcher_query.py "regular schedule and home base for N5854Z"
# Force the deterministic engine (fully offline):
python scripts/skywatcher_query.py --deterministic "what LZs does N767PD prefer?"
# Full profile dump / structured JSON:
python scripts/skywatcher_query.py --craft N5854Z
python scripts/skywatcher_query.py --json "what recurring routes are new?"
```

Intents recognised: schedule, home base, preferred LZs, recurring routes, new patterns,
fleet summary. (Co-occurrence lives in `scripts/rlsm_network_graph.py`.)

### HTTP

```bash
python -m uvicorn server.backend.main:app --port 8000
curl -s localhost:8000/api/entities/AircraftProfiles | jq '.[0]'
curl -s -XPOST localhost:8000/api/query \
  -H 'content-type: application/json' \
  -d '{"prompt":"home base for N5854Z"}' | jq
```

## LLM wrapper

`src/skywatcher/query/llm.py` reuses the `anthropic` client pattern from
`scripts/fr24_vision_ingest.py` (model default `claude-haiku-4-5-20251001`). The engine
assembles the grounded context; the model only *phrases* it under a system prompt that
forbids adding facts or inferring intent, and requires citing fields and surfacing
confidence/gaps. Install with `pip install -r requirements-llm.txt` and set
`ANTHROPIC_API_KEY`; without either, everything degrades to deterministic text.
