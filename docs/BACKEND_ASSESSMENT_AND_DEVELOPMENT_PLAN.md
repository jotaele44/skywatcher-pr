# Backend Assessment & Development Plan — skywatcher-pr

## Scope & method

Read-only assessment of the backend at `main` (`39e1fb2`, "fix(ingest_airports): require
--src, drop personal-machine default"). `skywatcher-pr` is the airspace/aircraft-
intelligence producer node in the PRII federation: it ingests FR24 screenshot data via OCR,
correlates flights/aircraft/tracks, and runs SATIM (satellite-imagery) analysis over the
Puerto Rico archipelago, exporting a federation package to `thehub-pr`.

This repo already maintains unusually thorough self-assessment docs —
`docs/MATURITY_AUDIT.md` (2026-07-26, execution-based, 63/100), `docs/ROAD_TO_100.md` +
`docs/unfinished_implementation_ledger.v1.json` (2026-08-04, 65.05/100), and
`federation.json`'s `federation_readiness_gate`. This document cross-references rather than
duplicates them, and flags where current `main` has already moved past what they report:
e.g. they record zero frontend tests, but `package.json` now wires `vitest` +
`@testing-library/react` + `vitest-axe` and 7 frontend test files exist. Treat this repo's
own numeric scores as a lower bound, not current truth.

## Tech stack & backend inventory

- **Framework**: FastAPI (`server/backend/requirements.txt`), no ORM/SQLAlchemy.
- **Storage**: direct file reads (JSONL/CSV/JSON) + raw `sqlite3` (read-only URI mode) for
  one operator-local RLSM database — deliberately no application-owned relational engine.
  Data model is expressed as 73 JSON Schemas + SQL DDL in `schemas/`, notably
  `schemas/database_schema.sql` (10-table FR24 canonical schema, versioned, idempotent,
  append-only history — documented in `docs/SKYWATCHER_DATABASE_SCHEMA.md`). A separate
  `data/rlsm/schema.sql` exists for the screenshot pipeline, being reconciled with the FR24
  schema per `docs/REPOSITORY_BOUNDARY_AUDIT.md`.
- **Endpoints**:
  - `server/backend/main.py` (841 lines): `/health`, `/api/health`,
    `/api/apps/public-settings`, `/api/analysis/registry`, `/api/auth/me` (always 401 by
    design — real auth deferred to `thehub-pr`), `POST /api/query` (NL/deterministic
    query engine), `/api/entities/{name}` (list/filter/get/availability),
    `POST /api/entities/{name}` and `PATCH /api/entities/{name}/{id}` (write-guarded,
    session-only, never persisted to disk).
  - `server/backend/console/router.py` (mounted at `/api/console`): `/capabilities`,
    `/repositories`, `/captures`, `/review/items`, `/aircraft/profiles`,
    `/aircraft/states`, `/flights` (+`/{id}`, `/{id}/track`), `/routes`,
    `/airports/{id}/operations` — backed by a real repository pattern
    (`server/backend/console/repositories/`, 2,082 LOC) with cursor pagination, bbox/
    time-window validation, and a provenance/source-taxonomy model.
- **Auth**: the write-path guard (`require_write_access`, `main.py` lines 96–128) —
  bearer-token via `PRII_WRITE_TOKEN` (constant-time compare) OR loopback/RFC1918/
  link-local origin only — is genuinely implemented and tested, not a stub. There is
  **no real user-auth backend**, by design (`/api/auth/me` always 401s). The frontend's
  Login/Register/password-reset pages call `/auth/*` routes that **do not exist** on this
  backend — flagged "DEAD" in `MATURITY_AUDIT.md` and correctly gated off
  (`App.jsx` only renders them when `authRequired` is true, which it never is here).
- **Business logic**: root-level `aircraft_intelligence.py`, `gis_intelligence.py`,
  `prii_readiness_engine.py`, `ilap_airspace_bridge.py`, `aasb_airspace_bridge.py`, 15
  `satim_*.py` modules; `src/skywatcher/{core,correlation,fusion,query,replay,fpim}`.
- **FR24 ingest pipeline** (`fr24/`, 81 files/~28k LOC): screenshot inventory/hashing,
  ensemble OCR, route extraction, georeferencing, a SQLite-backed manual-review queue,
  event export, SATIM engine runner.
- **Background jobs**: none in-process; scheduling lives in GitHub Actions
  (`adsb-poll.yml`, `maintenance.yml`).
- **Tests/CI**: 183 backend test files (807 passed/13 skipped per the July audit) plus 7
  frontend test files and a Playwright GUI-parity suite. 21 CI workflows; `ruff` is gated,
  but `mypy` runs with `continue-on-error: true` and `npm run typecheck` isn't wired into
  the `frontend` CI job at all (229 pre-existing TS/JS errors as of the July audit).

## Completion assessment

- **Fully implemented**: the read-only entity API and Phase-2 console API (both tested,
  with cursor pagination and a real provenance layer); write-path authorization (token or
  local-network gate); the FR24 ingest/OCR/route-extraction pipeline; the FR24 canonical
  schema + migrations; the export contract (`scripts/validate_airspace_export.py`); a
  24-entry capability-status registry (`console/capabilities.py`) that doubles as an
  honest, machine-checked backend roadmap.
- **Partially implemented**: type checking not gated (mypy report-only, `tsc` not run in
  CI); SATIM Phase 1/2 modules explicitly self-documented as stubs
  (`fr24/calibration/satim_candidate_extraction.py` and 3 siblings); ~11 of 24 console
  capabilities report `unavailable_no_adapter`/`unavailable_no_artifact` (bookmarks, recent
  selections, column config, unit preferences, map brightness/day-night overlay, aircraft
  styling, ATC overlays, oceanic tracks, airport badges/operations/weather); one open bug
  (`fr24_image_skill/orchestrator.py` doesn't catch `TesseractNotFoundError`, causing 6
  hard test failures instead of a graceful degrade — root cause and fix location already
  known).
- **Missing entirely**: real non-synthetic production export data (`federation.json`'s
  `ready_for_hub_live_execution: false`, 4 explicit blocking conditions); real auth backend
  (by design, deferred to `thehub-pr`); user-state persistence (no repository layer exists
  for the ~11 gated capabilities above); live ATC/oceanic-track/weather/disruption feed
  adapters.

## Development plan — hardest tasks first

Ordering rationale: items 1–3 are operator-data-gated or cross-repo architectural moves —
genuinely the hardest because they're bound by external inputs or another repo's design,
not local code quality — so they're sequenced first to surface blockers early rather than
build user-facing features against a foundation that may still shift. Items 4–5 are
substantial but fully within this repo's control.

1. **Land a non-synthetic, production-mode observation export** — Effort: **XL**,
   operator-gated. The repo's own top-ranked blocker: requires reconciling media identity
   across a materially complete reviewed screenshot corpus, wiring real geo-anchor data to
   replace the retired `places.geojson` dependency, and flipping the live-execution gate
   only on receipt evidence. A multi-stage pipeline problem gated on operator-supplied
   data, not a pure code task.
2. **Migrate external imagery acquisition/model execution to `thehub-pr` per ADR 0006** —
   Effort: **XL**, cross-repo. A cross-repository architectural boundary move — parity,
   dual-run, rollback, GUI, and retirement gates must all pass before the existing local
   imagery MCP path can be retired. Coordinate with `spiderweb-pr`'s plan doc (its own
   Skywatcher boundary-closure item depends on this).
3. **Reconcile the two divergent SQLite schemas** (`data/rlsm/schema.sql` vs. the FR24
   canonical `schemas/database_schema.sql`) — Effort: **L**, real migration risk. The
   reconciliation is designed (`docs/SKYWATCHER_DATABASE_SCHEMA.md`) but the merged schema
   has never run against a live operator corpus — a data-migration risk that only becomes
   real once item 1's real data exists, so validate this before or alongside item 1, not
   after.
4. **Build the Phase-4/6 user-state and map-runtime repositories** (bookmarks, recent
   selections, configurable columns, unit preferences, day/night overlay, aircraft styling,
   ATC overlays) — Effort: **L**. Zero backing persistence exists today; each of the ~11
   tracked capabilities needs a new repository plus console API surface — substantial but
   fully local, unlike items 1–2.
5. **Promote `mypy` to a gating CI check and wire `npm run typecheck` into CI** — Effort:
   **M**, deceptively large. 229 pre-existing TypeScript/JS errors across ~8.8k LOC of
   untyped JSX mean gating requires either fixing the backlog first or introducing a
   ratchet — a cross-cutting hygiene task touching the whole frontend.

## Quick wins (sequenced after/alongside the above, not skipped)

- Fix `fr24_image_skill/orchestrator.py` to catch `pytesseract.TesseractNotFoundError`
  alongside `ImportError` (root cause and fix location already documented:
  `orchestrator.py:188-190`) so a missing `tesseract` binary degrades gracefully.
- Reconcile the `requires_auth`/`auth_required` key-naming drift with `centinelas-pr` — same
  concept, two keys, one federation; a one-line rename plus doc update.
- Promote the already-clean, already-configured `mypy` step from `continue-on-error: true`
  to gating (Python side only — `ruff` is already gated).
- Incrementally move reusable logic out of `scripts/` (15.4k LOC, larger than `src/`) into
  `src/skywatcher/`, module by module.
