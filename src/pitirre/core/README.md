# PITIRRE Core

Core is the domain-neutral contract layer. This migration slice establishes the
first canonical implementations under `src/pitirre/core/` without renaming the
repository or rewriting historical SkyWatcher provenance.

## Active canonical surfaces

- `domains/registry.py` — physical-domain identity and exact path validation.
- `contracts/observation.py` — lossless cross-domain observation envelope.
- `contracts/air_event.py` — AIR event v2 schema loading/validation.
- `normalization/air_event.py` — nullable-geometry AIR normalization.

## Dependency rule

Core may use the standard library and declared third-party contract/runtime
dependencies. It must not import SATIM, FPIM, CORRIM or Legacy analytical code.

## Planned Core families

The repository map reserves provenance, evidence, identity, temporal, spatial,
knowledge, replay, registries, readiness, governance and federation families.
They are migrated only when their manifest rows reach their own parity gates;
empty directories are not created merely to make the target tree look complete.

## Compatibility

Historical imports remain callable through thin wrappers under both
`skywatcher.*` and `pitirre.compat.skywatcher.*`. Canonical implementation
logic lives only under `pitirre.core.*`.
