# ADR — PITIRRE domain model v0.1

**Status:** CANDIDATE BINDING / ADDITIVE FOUNDATION  
**Frozen source baseline:** `jotaele44/skywatcher-pr@afbf2f8ea31e9fdd449f0d369727022956817213`  
**Stable GitHub repository ID:** `1261399537`  
**Repository rename state:** NOT EXECUTED

## Decision

The proposed successor system identity is **PITIRRE**. The canonical top-level
domain denominator is:

```text
AIR | LAND | WATER | SPACE
```

ROAD is **not** a fifth top-level domain. It is a first-class network family:

```text
LAND.TRANSPORT.ROAD
```

This preserves road topology, routing, access, closure and temporal-state
semantics without forcing every transport network to become a peer physical
domain.

## Why ROAD is nested

ROAD has distinct network behavior, but remains physically and semantically
contained by LAND. The architecture therefore separates three axes:

```text
domain
subdomain
network_type
```

For a road-segment observation:

```text
domain       = LAND
subdomain    = TRANSPORT
network_type = ROAD
```

This avoids treating LAND × ROAD as a cross-domain correlation. A facility
event and a road closure are both LAND observations with different subdomain
semantics.

## Existing repository evidence reused

The transformation is not greenfield.

- AIR is the existing SkyWatcher lineage and remains the dominant implemented
  capability.
- SPACE already exists in the repository operating contract and in the
  Space-Track draft implementation.
- WATER/MARITIME already has source-registry, schema and cross-domain fusion
  artifacts.
- ROAD already appears in SATIM feature detectors, but only as imagery/feature
  semantics; canonical network state/topology is not yet implemented.
- LAND is therefore the largest missing top-level ontology binding.

Existing passed artifacts are reused. Historical artifacts are not rewritten
simply because the future system name changes.

## Authority boundary

PITIRRE owns observation, event, temporal-state, replay, anomaly and
cross-domain correlation semantics.

Spiderweb remains the federation spatial/geometry authority. Where ROAD
topology is sourced authoritatively elsewhere, PITIRRE references that geometry
and records temporal network state rather than silently claiming geometric
authority.

AguaYLuz remains the water-system/hydrologic authority where applicable.

## Identity and evidence invariants

- repository name != repository identity
- name equality != entity identity
- ROAD adjacency != connectivity
- ROAD proximity != access
- geometry intersection != legal/operational access
- co-location != relationship
- relationship != causation
- implication != fact
- repeated manifestations from one source lineage != independent corroboration

No normalization operation may itself establish canonical identity.

## Migration rule

The repository must be transformed additively:

1. Freeze exact current `main`.
2. Introduce the domain registry and tests.
3. Preserve AIR behavior.
4. Promote existing SPACE and WATER/MARITIME primitives into the registry.
5. Add LAND and LAND.TRANSPORT.ROAD contracts.
6. Generalize correlation to domain-agnostic observations/events.
7. Rename repository identity only through an explicit rename stage.
8. Reconcile federation consumers.
9. Certify bounded scopes only after arithmetic closure and zero unresolved
   residue within the claim.

A global `skywatcher -> pitirre` replacement is prohibited because it would
rewrite historical provenance and conflate AIR-specific lineage with generic
system identity.
