# ADR: Skywatcher-Spiderweb Integration Boundary

## Status

Accepted.

## Decision

Skywatcher and Spiderweb integrate through the federation hub contract, not through a bespoke point-to-point connector.

Skywatcher owns FR24-derived airspace ingestion, OCR, normalization, and canonical airspace package production.

Spiderweb does not import Skywatcher code directly. If Spiderweb later needs Skywatcher observations for spatial correlation, it may consume the same canonical package emitted by Skywatcher and validated by thehub-pr.

## Rationale

The federation architecture is hub-and-spoke. Producers emit canonical packages. thehub-pr discovers, validates, and aggregates those packages.

A direct Skywatcher-to-Spiderweb pipe would create a second integration channel, duplicate contract logic, and re-couple repositories that were just separated.

## Required Sequence

1. Skywatcher emits a live, non-synthetic canonical federation package.
2. thehub-pr validates and aggregates that package.
3. Spiderweb completes geometry-on-entities support for spatial joins.
4. Only then may Spiderweb add a thin Skywatcher package adapter, using the same canonical export contract.

## Rejected Options

### Bespoke direct connector

Rejected because it creates split authority and format drift.

### Re-importing Skywatcher code into Spiderweb

Rejected because it reverses the FR24 migration boundary.

### Building the Spiderweb adapter before live exports and geometry support

Rejected because it would be dead wiring.

## Consequence

The canonical integration path is:

```text
skywatcher-pr -> canonical package -> thehub-pr -> federation graph
```

A later Spiderweb consumer path is allowed only as:

```text
skywatcher-pr -> same canonical package -> spiderweb-pr spatial query adapter
```

---

## Revision 2026-07-20 — hub-canonical Spiderweb consumer implemented

The FR24 screenshot-processing capability now lives entirely in Skywatcher.
Per the "Required Sequence" above, the Spiderweb consumer is implemented as a
**thin hub-canonical package adapter**, NOT a bespoke point-to-point connector:

```text
skywatcher-pr  --export-spiderweb DIR   (canonical hub package: manifest.json +
                                         bridge_records.jsonl of spiderweb_bridge)
      │
      ▼
spiderweb-pr   run_all.py --ingest-skywatcher DIR
      │  → integration/skywatcher_bridge.ingest_package()
      │  → schema-validate each record against schemas/spiderweb_bridge.schema.json
      │  → route valid records into flights / track_points for downstream correlation
```

The shared contract (`schemas/spiderweb_bridge.schema.json`) is maintained
identically in both repositories. Spiderweb imports NO Skywatcher code; it only
consumes the validated package. This satisfies the ADR's requirement that any
Spiderweb consumer use the same canonical export contract, and encodes the
cross-repo semantic reconciliations (confidence object, review-status crosswalk,
widened coordinate-method enum, gated mission classification, prohibited
terminal-accept labels). See docs/REPOSITORY_BOUNDARY_AUDIT.md.
