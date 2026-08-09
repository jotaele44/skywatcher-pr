# ADR 0006 S06 legacy shadow projection foundation

S06 freezes an offline `legacy_shadow_export.v1` record and pure projection helpers for TheHub H08 dual-run lane evidence. It does not execute the deprecated FR24 provider path, access credentials, read or write RLSM databases, launch workers, call providers/models, certify evidence, promote snapshots, or authorize retirement.

The legacy export preserves actual CSV column names and requires explicit provider/model/prompt/policy/source provenance. Missing provenance fails closed and is never inferred. All serialized paths are package-root relative and secret-shaped keys are rejected.

The candidate projection consumes already-built S05 package data plus required H06/H07 identifiers and emits only caller-supplied H08 lane-evidence inputs. Generic execution-receipt signature verification remains TheHub-owned and is not performed here.

Frozen schema SHA-256:

`fd1e191abeddd3ae821c70482fef7ed8d3ab53e24c01d31a5dfeb154d6df1812  schemas/ai_imagery/legacy_shadow_export.v1.schema.json`
