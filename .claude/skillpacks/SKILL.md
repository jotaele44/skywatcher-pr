---
name: skywatcher-pr-unified-live-skillpack
description: "Compiled non-activating dispatch contract."
version: 1.0.1
compatibility: claude
repository: skywatcher-pr
---

# skywatcher-pr Unified Live Skillpack

Pinned base: `aade1d3ffe8119752cd9282327a91d73e5bca577`.

## Execution contract

- Exact identifiers only; unknown identifiers fail closed.
- Runtime activation, automatic dispatch, polling, notifications, writes, promotion, control, merge, and release are disabled.
- Module and package hashes remain in `MANIFEST.json`.

## Capability dispatch

| Capability | Module | Status | Preserved responsibility |
|---|---|---|---|
<a id="capability-repo-state-reader"></a>| `repo-state-reader` | `repository-governance` | `preserved-active-contract` | Preserve `repo-state-reader` under `repository-governance`. |
<a id="capability-repo-identity-guard"></a>| `repo-identity-guard` | `repository-governance` | `preserved-active-contract` | Preserve `repo-identity-guard` under `repository-governance`. |
<a id="capability-branch-guard"></a>| `branch-guard` | `repository-governance` | `preserved-active-contract` | Preserve `branch-guard` under `repository-governance`. |
<a id="capability-task-scope-guard"></a>| `task-scope-guard` | `repository-governance` | `preserved-active-contract` | Preserve `task-scope-guard` under `repository-governance`. |
<a id="capability-git-action-guard"></a>| `git-action-guard` | `repository-governance` | `preserved-active-contract` | Preserve `git-action-guard` under `repository-governance`. |
<a id="capability-skill-authoring-template"></a>| `skill-authoring-template` | `skill-lifecycle` | `preserved-active-contract` | Preserve `skill-authoring-template` under `skill-lifecycle`. |
<a id="capability-skill-package-builder"></a>| `skill-package-builder` | `skill-lifecycle` | `preserved-active-contract` | Preserve `skill-package-builder` under `skill-lifecycle`. |
<a id="capability-validation-gate-runner"></a>| `validation-gate-runner` | `validation-and-recovery` | `preserved-active-contract` | Preserve `validation-gate-runner` under `validation-and-recovery`. |
<a id="capability-failure-packet-builder"></a>| `failure-packet-builder` | `validation-and-recovery` | `preserved-active-contract` | Preserve `failure-packet-builder` under `validation-and-recovery`. |
<a id="capability-delta-reporter"></a>| `delta-reporter` | `reporting-and-receipts` | `preserved-active-contract` | Preserve `delta-reporter` under `reporting-and-receipts`. |
<a id="capability-status-writer"></a>| `status-writer` | `reporting-and-receipts` | `preserved-active-contract` | Preserve `status-writer` under `reporting-and-receipts`. |
<a id="capability-foia-correspondence-manager"></a>| `foia-correspondence-manager` | `foia-operations` | `preserved-active-contract` | Preserve `foia-correspondence-manager` under `foia-operations`. |
<a id="capability-foia-request-sender"></a>| `foia-request-sender` | `foia-operations` | `preserved-active-contract` | Preserve `foia-request-sender` under `foia-operations`. |
<a id="capability-skywatcher-operator"></a>| `skywatcher-operator` | `orchestration-and-readiness` | `preserved-active-contract` | Preserve `skywatcher-operator` under `orchestration-and-readiness`. |
<a id="capability-skywatcher-readiness-auditor"></a>| `skywatcher-readiness-auditor` | `orchestration-and-readiness` | `preserved-active-contract` | Preserve `skywatcher-readiness-auditor` under `orchestration-and-readiness`. |
<a id="capability-airspace-export-validator"></a>| `airspace-export-validator` | `orchestration-and-readiness` | `preserved-active-contract` | Preserve `airspace-export-validator` under `orchestration-and-readiness`. |
<a id="capability-fr24-screenshot-inventory"></a>| `fr24-screenshot-inventory` | `fr24-acquisition` | `preserved-active-contract` | Preserve `fr24-screenshot-inventory` under `fr24-acquisition`. |
<a id="capability-fr24-route-extractor"></a>| `fr24-route-extractor` | `fr24-acquisition` | `preserved-active-contract` | Preserve `fr24-route-extractor` under `fr24-acquisition`. |
<a id="capability-track-termination-event-classifier"></a>| `track-termination-event-classifier` | `flight-event-analysis` | `preserved-active-contract` | Preserve `track-termination-event-classifier` under `flight-event-analysis`. |
<a id="capability-aircraft-registry-enricher"></a>| `aircraft-registry-enricher` | `flight-event-analysis` | `preserved-active-contract` | Preserve `aircraft-registry-enricher` under `flight-event-analysis`. |
<a id="capability-aircraft-intelligence-profiler"></a>| `aircraft-intelligence-profiler` | `flight-event-analysis` | `preserved-active-contract` | Preserve `aircraft-intelligence-profiler` under `flight-event-analysis`. |
<a id="capability-satim-engine"></a>| `satim-engine` | `satim-evidence-engine` | `preserved-active-contract` | Preserve `satim-engine` under `satim-evidence-engine`. |
<a id="capability-satim-engine-operator"></a>| `satim-engine-operator` | `satim-evidence-engine` | `preserved-active-contract` | Preserve `satim-engine-operator` under `satim-evidence-engine`. |
<a id="capability-satim-flight-gis-evidence"></a>| `satim-flight-gis-evidence` | `satim-evidence-engine` | `preserved-active-contract` | Preserve `satim-flight-gis-evidence` under `satim-evidence-engine`. |
<a id="capability-skywatcher-airspace-evidence"></a>| `skywatcher-airspace-evidence` | `satim-evidence-engine` | `preserved-active-contract` | Preserve `skywatcher-airspace-evidence` under `satim-evidence-engine`. |
<a id="capability-ilap-airspace-bridge"></a>| `ilap-airspace-bridge` | `spatial-bridges` | `preserved-active-contract` | Preserve `ilap-airspace-bridge` under `spatial-bridges`. |
<a id="capability-aasb-spatial-bridge"></a>| `aasb-spatial-bridge` | `spatial-bridges` | `preserved-active-contract` | Preserve `aasb-spatial-bridge` under `spatial-bridges`. |
<a id="capability-terrain-access-candidate"></a>| `terrain-access-candidate` | `experimental-terrain` | `preserved-active-contract` | Preserve `terrain-access-candidate` under `experimental-terrain`. |
<a id="capability-skywatcher-skill-package-template"></a>| `skywatcher-skill-package-template` | `compatibility-authoring` | `compatibility-alias` | Preserve `skywatcher-skill-package-template` as an alias of `skill-authoring-template`. |

## Required receipt fields

`capability_id`, `repository`, `pinned_base_commit`, `inputs`, `outputs`, `validation`, `limitations`, `authority`, and `next_action`.

## Non-activation boundary

This binding does not invoke repository code. Runtime adapters require separate authorization.
