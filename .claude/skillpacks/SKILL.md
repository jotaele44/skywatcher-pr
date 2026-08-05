---
name: skywatcher-pr-unified-live-skillpack
description: "Compiled non-activating dispatch contract for shared and skywatcher-pr capabilities."
version: 1.0.0
compatibility: claude
repository: skywatcher-pr
---

# skywatcher-pr Unified Live Skillpack

Pinned base: `aade1d3ffe8119752cd9282327a91d73e5bca577`.

## Execution contract

- Exact capability identifiers only; unknown identifiers fail closed.
- Runtime activation, automatic dispatch, live polling, notifications, external writes, promotion, control actions, merge, and release are disabled.
- Source module semantics remain cryptographically bound in `MANIFEST.json`; this file is the compiled live dispatcher.
- Repository-specific authority overrides shared defaults.

## Capability dispatch

| Capability | Module | Status | Preserved responsibility |
|---|---|---|---|
| `repo-state-reader` | `repository-governance` | `` |  |
| `repo-identity-guard` | `repository-governance` | `` |  |
| `branch-guard` | `repository-governance` | `` |  |
| `task-scope-guard` | `repository-governance` | `` |  |
| `git-action-guard` | `repository-governance` | `` |  |
| `skill-authoring-template` | `skill-lifecycle` | `` |  |
| `skill-package-builder` | `skill-lifecycle` | `` |  |
| `validation-gate-runner` | `validation-and-recovery` | `` |  |
| `failure-packet-builder` | `validation-and-recovery` | `` |  |
| `delta-reporter` | `reporting-and-receipts` | `` |  |
| `status-writer` | `reporting-and-receipts` | `` |  |
| `foia-correspondence-manager` | `foia-operations` | `` |  |
| `foia-request-sender` | `foia-operations` | `` |  |
| `skywatcher-operator` | `orchestration-and-readiness` | `` |  |
| `skywatcher-readiness-auditor` | `orchestration-and-readiness` | `` |  |
| `airspace-export-validator` | `orchestration-and-readiness` | `` |  |
| `fr24-screenshot-inventory` | `fr24-acquisition` | `` |  |
| `fr24-route-extractor` | `fr24-acquisition` | `` |  |
| `track-termination-event-classifier` | `flight-event-analysis` | `` |  |
| `aircraft-registry-enricher` | `flight-event-analysis` | `` |  |
| `aircraft-intelligence-profiler` | `flight-event-analysis` | `` |  |
| `satim-engine` | `satim-evidence-engine` | `` |  |
| `satim-engine-operator` | `satim-evidence-engine` | `` |  |
| `satim-flight-gis-evidence` | `satim-evidence-engine` | `` |  |
| `skywatcher-airspace-evidence` | `satim-evidence-engine` | `` |  |
| `ilap-airspace-bridge` | `spatial-bridges` | `` |  |
| `aasb-spatial-bridge` | `spatial-bridges` | `` |  |
| `terrain-access-candidate` | `experimental-terrain` | `` |  |
| `skywatcher-skill-package-template` | `compatibility-authoring` | ``; alias of `skill-authoring-template` |  |

## Required output fields

Every execution receipt must include `capability_id`, `repository`, `pinned_base_commit`, `inputs`, `outputs`, `validation`, `limitations`, `authority`, and `next_action`.

## Non-activation boundary

This binding does not invoke repository code. A later runtime adapter requires separate design, tests, review, and explicit authorization.
