# Frozen GloTEC transport RC1

Scope: an internal versioned producer adapter and persisted exact export for the
Aguayluz disabled ionosphere preview. No live refresh, ROTI calculation, operational
activation, or station/municipality/asset identity is introduced.

Repository ID 1261399537; base 770517f42fdd8aa90b89faebf3069795e564913b.
The existing observation v1 schema and existing adapters are unchanged. New v2
uses pitirre-observation-v0.2 and a glotec_model legacy_contract under
SPACE.SPACE_WEATHER, with operational_use_allowed=false. A source point is a
MODEL_GRID_NODE, never a receiver station. Raw features and source indices remain
intact inside payload. The observation ID binds an immutable raw SHA256 and row
index only, not a physical entity.

Input: tests/fixtures/ionosphere/glotec_20261023T163500Z.zip, reused byte-for-byte
from Aguayluz's passing CI capture run 39991895111, artifact 12518166220.
Archive SHA256: b089a7d7e540f2809dab6d6fb0901226f961980e3fe055e020fcdbc745ad64e8.
Raw source SHA256: 511f8418b3a5b8f1a5058ca6045970ad9b5dd62647eb6202a2f5cd5d6ce0393b.
No mutable source was redownloaded to construct this producer export.

All 5,184 grid positions are validated before selecting 6 regional context rows;
5,178 are excluded. Selection bbox [-70,16,-60,22] is discovery context only.
Export: exports/ionosphere/glotec_context.package.json; serialization and code/schema
blob bindings: exports/ionosphere/manifest.json. The Aguayluz consumer receives
these exact bytes and validates version, producer ID, package/schema digests,
row conservation, every source index, raw feature, epoch, coordinate role and policy.
Idempotent replay is read-only; no authoritative database rows are written.

Local source transport and legacy regressions pass. Exact new-head CI is a separate
gate. A transport PASS does not establish current provider health or production
readiness. Existing NON_PRODUCTION_DIAGNOSTIC/readiness locks are unchanged.

Rollback: leave consuming preview flags disabled, or revert this additive adapter,
v2 schema and export files. V1 schema/legacy contracts remain available.
Reusable skill promotion is withheld until the adopted complete vector passes.
