# Sky Core mount migration v0.1 — proposed, not certified
Operation: sky-core-v0.1.0/gate-02/design
Baseline: 5cc54b2f146dc958b9c8fe39fd03bc4e1b8ff141
Inventory checkpoint: ca829c3150aaf25f8ce726441b186c7dd03fca58

## Binding constraints
Reuse core/lenses LensSpec, LensRegistry, ObjectiveProfileRegistry, coverage and threshold contracts; do not create a parallel lens registry. A mount is an executable domain capability, while a lens is a declarative objective. Multiple lenses can bind to a mount. Preserve existing import boundaries and compatibility shims. CORRIM alone combines SATIM and FPIM findings. RLSM remains a Core-governed extraction pipeline. FLIPA identity is unresolved; no invented alias or implementation.

## Proposed executable binding
Use a composition-root allowlist of trusted adapters, never arbitrary imports or commands from configuration. Bind exact lens ID/version/config digest, adapter version and source commit, input/output schema, dependency identities, calibration/threshold receipts and qualification evidence. Active metadata is not production qualification. Empty mount selection permits evidence preparation but cannot certify an analytical objective. Existing objective profiles requiring lenses retain their semantics. No changes to live defaults until parity passes.

## Gates
1. PARTIAL: recursive tree captured; reconcile all specs, tests, objective profiles, workflows and FLIPA references/history; execute exact-head baseline tests.
2. OPEN: prove empty-core boot, trusted adapter discovery, unchanged legacy workflows and rejection of missing/stale qualification.
3. OPEN: SATIM isolated execution, frozen calibration, holdout benchmark, legacy parity and evidence schema validation. Start with image artifacts; no cross-domain inference.
4. OPEN: FPIM endpoint candidates, label-independent replay, quarantine enforcement and generality without changing existing semantics.
5. BLOCKED by 2–4: typed artifact dependencies, shared preprocessing keyed by input/config digest, CORRIM reconciliation, selective descendant invalidation, GUI/backend parity.

## Execution and promotion
TheHub owns durable supervision and governance; Skywatcher owns analytical semantics. Mucaro may recommend only eligible mounts. No duplicated authorization. No production promotion until mandatory gates pass at exact head. Desktop Commander monthly quota exhausted; persistent execution and recovery tests unverified. This document and inventory are Git checkpoints, not a running supervisor or immutable external audit ledger.
