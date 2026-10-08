# Blockers and unblock plan — skywatcher-pr (2026-09-28)

**Audit date:** 2026-09-28 · **`main` at audit:** `cfc0183` (not branch-protected) · **Production status:** `NON_PRODUCTION_DIAGNOSTIC`. The hub export is 16/16 synthetic, consistent with that declaration.

**Post-audit update (2026-09-28 20:35Z):** the record_cell_binding v0.2 series was pushed straight to `main` after the audit. The Cell_Set PR #328 now conflicts with `main` and is superseded (X-05). The same series left `ruff check .` red on `main` (X-10); this PR carries the one-line fix.

This document lists every blocker that the repository, its CI, and its GitHub issues and pull requests recorded as of the audit date, then gives an ordered plan to clear them. It changes no code, gate, ledger, or status file.

Cross-repository blockers (IDs `X-nn`) are described in full in
`jotaele44/thehub-pr` → `docs/BLOCKERS_AND_UNBLOCK_PLAN_2026-09-28.md`.

## How this inventory was built

Sources checked:

- all 4 open issues and all 17 open pull requests;
- CI on `main`, for push and scheduled runs (`adsb-poll` is green);
- per-PR check results from the thehub federation completion-gate artifact (run `36326861596`, 2026-09-27 14:42Z);
- `docs/unfinished_implementation_ledger.v1.json`, reconciled against PR history;
- `docs/ROAD_TO_100.md` and `AUDIT.md`;
- thehub `docs/FEDERATION_MAX_AUDIT_2026-09-24.md`;
- the branch list and branch protection.

## Summary

Each blocker is counted once, under its primary type.

| Type | Count |
|---|---:|
| DATA (operator run or external data) | 6 |
| GATE | 1 |
| IMPL | 3 |
| GOV | 1 |
| PR | 1 group (17 PRs) |
| STALE | 1 |
| **Total** | **13** |

## Blocker inventory

| ID | Blocker | Type | Evidence | Owner | Unblock step | Exit criterion |
|---|---|---|---|---|---|---|
| SK-01 | Aircraft spatial truth has not been run on the full operator corpus | DATA (operator run) | Ledger SKY-001. #171 merged 2026-08-12; `docs/ROAD_TO_100.md` exit step 1 | Operator | Run the complete local screenshot corpus | Terminal accounting, zero false bindings, no published error above 500 m |
| SK-02 | No operator receipts for multisensor replay | DATA (operator run) | Ledger SKY-002. #170 merged 2026-08-12 | Operator | Produce byte-identical replay receipts | Receipts validated with terminal checks |
| SK-03 | Standalone packaging of the isolated-clone runtime is not certified | GATE | Ledger SKY-003. #172 merged | Agent/maintainer | Certify install, test and package from a clean `main` clone | Packaging certification receipt |
| SK-04 | Geocoding still depends on the obsolete `places.geojson` | DATA | Ledger SKY-005; `docs/ROAD_TO_100.md` step 3 | Operator | Supply a tracked, provenance-bound gazetteer and geo-anchor inputs | Geocoding and anchor seeding run from tracked inputs; with zero keys they fail closed |
| SK-05 | No real FR24 production export | DATA/IMPL | Ledger SKY-006; #7 (airfield, helipad and hangar registries, endpoint attribution, a non-synthetic `airspace_observation` package, production-mode validation) | Operator (licensed captures) + agent | Obtain licensed or authorized captures, then implement the #7 tasks | `scripts/validate_airspace_export.py <pkg> --mode production` passes on real data and rejects synthetic rows |
| SK-06 | Terrain, imagery and enrichment layers are not ported | DATA | Ledger SKY-007: lineage, licensing and source artifacts | Operator/maintainer | Port GEBCO, imagery and ILAP layers with independent provenance | Layers present with licensing recorded |
| SK-07 | ILAP calibration corpora are not acquired | DATA | #282. Every class denominator is still open (palm and tree morphology, roof/tarp/pool/glare, vehicle baselines, path networks, access friction). The NOAA Maria 2017 pilot (dataset 8507, item `20170924bC0660430w183000n`) has a frozen dry-run plan and CC0 rights. Its fetch was blocked only because the agent environment had no outbound network. | Agent with network + operator | Run the pilot fetch in a network-enabled runner such as a GitHub Actions `workflow_dispatch`; then acquire the remaining classes | Class denominators frozen, no lineage leakage, arithmetic closes |
| SK-08 | The SATIM → ILAP scene graph and detector stack is not implemented | IMPL | #279. The composite ILAP score stays disabled until calibrated. | Agent | Implement the detectors and pass each subsystem's positive and negative gates | Each subsystem certified independently |
| SK-09 | FAA Registry Certification v1 is not implemented | IMPL | #240. The current validator hard-codes `N253TH`; there are no frozen source hashes and no arithmetic gates. | Agent | Implement the content-addressed certification in the issue spec | `FAA_REGISTRY_CERTIFIED` on a frozen FAA snapshot |
| SK-10 | The vendored federation schema is stale | IMPL | thehub MAX audit F6. `schemas/federation_entity.schema.json` requires `location.{lat,lon}`, which rejects 84 of 207 hub-valid moneysweep entities (40.6%). The alert schema lacks `is_critical`. | Agent | Re-vendor the hub schemas, or source them from the hub pin | The consumer ingests the moneysweep package with 0 rejects |
| SK-11 | Open PRs have conflicts, red checks or need migration | PR | See the next table | Agent + maintainer | Per-PR actions below | No red or conflicting PRs |
| SK-12 | Skill-governance phases SG1–SG4 are blocked because SG0 was never certified | GOV | Ledger SKY-008. #176 (SG0) was closed unmerged on 2026-09-03; the road-to-100 rule keeps SG1–SG4 blocked until SG0 is certified | Maintainer | Re-ballot SG0 or formally retire the governance track | Decision recorded |
| SK-13 | `AUDIT.md` claims a gap that does not exist | STALE | It says `server/backend/console/` is empty; it contains `router.py`, `capabilities.py`, `fr24_control_plane.py`, `migrations.py` and 6 more modules | Agent | Correct `AUDIT.md` | Doc accurate |

### Open pull requests (SK-11)

| PR | State | Action |
|---|---|---|
| #328 Cell_Set uncertainty contract | Conflicts with `main` since the post-audit v0.2 series, which already carries the contract in `federation/spatial/registry_version.json` | Confirm v0.2 covers it, then close as superseded (X-05) |
| #324 correlation detector v1 | No merge commit (conflict); overlaps 1 path on current `main` | Rebase, rerun, review |
| #300 V4 family split summary | No merge commit (conflict); overlaps 4 paths | Rebase and reconcile |
| #299 ILAP visual review (draft) | Conflict; overlaps 5 paths; GUI Reachability E2E red | Rebase and reconcile, or close as superseded |
| #321 Space-Track control plane (draft) | RED: builds × 3, tests 3.10–3.12 | Fix or close |
| #315 react-dom | RED: E2E, frontend, builds × 3 | Migrate, or ignore the major (X-02) |
| #312 eslint 10 | RED: 5 checks | Migrate, or ignore the major |
| #310 date-fns 4 | RED: 5 checks | Migrate, or ignore the major |
| #313 setup-uv 10.1, #311 actions group | RED: Federation template drift | Land the bump via thehub `federation-templates`, re-render, close these PRs |
| #307 pyarrow ≥ 25, #306 numpy ≥ 2.2.6, #304 opencv 5 | RED: lock | Regenerate `uv.lock` with each bump, or ignore the majors |
| #305 fastmcp ≥ 4 | RED: test-imagery 3.11/3.12, lock | Migrate plus lock, or ignore the major |
| #314 jsdom 30, #309 npm group, #308 anthropic ≥ 1.7 | Green | Update the branch and merge |

## Unblock plan

### P1 — executable now
1. **SK-10:** re-vendor the hub entity and alert schemas.
2. **SK-11:** rebase #324 and #300; merge the green dependabot PRs; route #311 and #313 through thehub templates; regenerate locks.
3. **SK-13:** correct `AUDIT.md`.
4. **SK-07:** dispatch the NOAA Maria pilot fetch in a network-enabled runner.

### P2 — operator inputs
1. **SK-01, SK-02:** full-corpus spatial-truth run and replay receipts.
2. **SK-04:** gazetteer and geo-anchor inputs.
3. **SK-05:** licensed FR24 captures.
4. **SK-06:** licensed terrain and imagery layers.

### P3 — maintainer decisions
1. **SK-12:** decide on SG0.
2. Branch protection on `main` (X-03).
3. Dispose of the draft PRs #299 and #321.

### P4 — longer horizon
1. **SK-05:** #7 non-synthetic export.
2. **SK-08:** #279 detector stack.
3. **SK-09:** #240 FAA certification.
4. **SK-03:** packaging certification.

## Ledger reconciliation (`docs/unfinished_implementation_ledger.v1.json`, dated 2026-08-04)

| Ledger ID | Ledger state | State on 2026-09-28 |
|---|---|---|
| SKY-001 | merged_operator_run | Code on `main`; operator run still open → SK-01 |
| SKY-002 | merged_operator_run | Code on `main`; receipts still open → SK-02 |
| SKY-003 | merged_certification_pending | Still open → SK-03 |
| SKY-004 | rescue_pr (PR-173) | Resolved: #173 closed unmerged 2026-09-03 (still check that `places.geojson` was not promoted) |
| SKY-005 | operator_input | Still open → SK-04 |
| SKY-006 | operator_run | Still open → SK-05 |
| SKY-007 | external_data | Still open → SK-06 |
| SKY-008 | governance_only (PR-176) | #176 closed unmerged → SK-12 |

## Hygiene
- 52 branches on origin, including `tmp-do-not-use-satim`, `tmp2-do-not-use-satim`, `rescue-stash-0` and `backup/*`. Prune them and keep `freeze/*` and `archive/*`.

## Federation-wide blockers that affect this repo
- X-01: completion gate.
- X-02: dependabot backlog and template drift.
- X-03: `main` is unprotected.
- X-05: the Cell_Set PR set, now superseded by v0.2 on `main`.
- X-07: stale ledgers.
- X-10: `main` lint is red since the v0.2 series; this PR carries the fix.

See the thehub document for details.

## Not verifiable with the access used for this audit
- Code-scanning and Dependabot security-alert inventories.
- The operator's local screenshot and FR24 corpora.
- Actions secrets.
