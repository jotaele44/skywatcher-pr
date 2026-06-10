# ADR: How Skywatcher airspace data reaches Spiderweb

**Status:** Accepted (decision recorded; direct adapter deferred)
**Date:** 2026-06-09
**Repos:** `skywatcher-pr` (producer), `spiderweb-pr` (query-hub consumer), `thehub-pr` (federation hub)

## Context

After the FR24 ingest/OCR pipeline was migrated out of spiderweb into skywatcher,
skywatcher (`federation_role: airspace_intelligence_node`) is the producer of airspace
observations, and spiderweb (`federation_role: spatial_operational_query_hub`) is a
dual producer/consumer whose query-hub already ingests other producers' packages
(e.g. the contract-sweeper adapter at `federation/hub/adapters/contract_sweeper.py`).

Question: should skywatcher's airspace data reach spiderweb **through `thehub-pr`**, or
via a **direct** skywatcher→spiderweb link?

## Decision

**Route through the hub. Do not build a bespoke point-to-point link.** A future
direct read by spiderweb's query-hub is allowed, but only as an ingest of the *same*
canonical package skywatcher already emits — and it is **deferred** until two
preconditions are met.

### Rationale

- `thehub-pr` is the designed integration plane: it discovers producers, validates their
  exports against the shared contract, and aggregates them into one cross-domain graph.
  Skywatcher is already registered in `thehub-pr/registry/producers.yaml`, so the hub
  path needs **no new code** — only a live export from skywatcher.
- The repos were deliberately decoupled in the migration. Exchange must stay **file-based
  via the canonical package contract** (`sources`/`entities`/`relationships`/
  `observations` JSONL + manifest). No cross-repo code imports, no second format.
- A direct adapter is a legitimate optimization *within spiderweb's consumer role* (for
  spatial correlation of airspace vs. its other domains), not a parallel channel.

## Preconditions for the (optional) direct adapter

1. **Skywatcher emits a live canonical package.** `scripts/federation_export.py` must
   produce a real (non-synthetic) observation export. Until then there is nothing to
   consume on either path. (Skywatcher readiness-gate blocker.)
2. **Spiderweb carries geometry on canonical entities.** Spiderweb's readiness gate notes
   `correlate_spatial` has no entity geometry to join on until the Z2 follow-up projects
   geometry onto canonical entities. Until then a skywatcher adapter would have nothing to
   spatially join — dead wiring.

## Consequences / sequence

1. **Now:** finish skywatcher's live canonical export → `thehub-pr` aggregates it. This is
   the only required work and unblocks the federation graph for everyone.
2. **Then:** complete spiderweb's geometry-on-entities (Z2) work.
3. **Then (optional):** add `federation/hub/adapters/skywatcher.py` to spiderweb, mirroring
   `contract_sweeper.py`, that ingests skywatcher's canonical package into the spatial
   lane (`federation/hub/layer_registry.py`) via `scripts/ingest_*`. Same package the hub
   reads — one package, two consumers.

## Explicitly rejected

- A bespoke skywatcher→spiderweb pipe or a spiderweb-specific export format.
- Re-importing skywatcher code into spiderweb (re-couples what the migration separated).
- Building the spiderweb adapter before both preconditions clear.
