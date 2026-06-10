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
