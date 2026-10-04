# PITIRRE Repository Map v1 — Contradiction Ledger

**Source snapshot:** `main@2100e6527d49abc302b804d3175feea9ce614eb4`  
**Scope:** contradictions discovered while classifying the complete 1,363-file Git tree.

## PITIRRE-C001

- **Class:** GEOMETRY
- **State:** OPEN
- **Path:** `src/skywatcher/normalizers/air_event_normalizer.py`
- **Observed implementation:** the generic `_float` helper defaults to `0.0`;
  latitude and longitude are normalized through that helper without a distinct
  missing-coordinate sentinel.
- **Contradiction:** PITIRRE requires unknown coordinates to remain
  NULL/NONE/UNRESOLVED. Missing is not the geographic coordinate zero.
- **Failure mode:** a missing coordinate silently becomes `(0,0)`, so spatial
  logic can succeed wrong rather than fail closed.
- **Required repair:** preserve source raw coordinate strings; parse into
  nullable numeric fields; distinguish invalid from missing; reject or
  explicitly retain unknown geometry; add positive and negative regressions.
- **Migration gate:** `BLOCKED_GEOMETRY_NULL_SEMANTICS`.

## PITIRRE-C002

- **Class:** CLASS / GOVERNANCE
- **State:** OPEN
- **Paths:** `docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md`,
  `docs/architecture/ADR_SKYWATCHER_ANALYTICAL_ONTOLOGY_v2_1.md`,
  `src/skywatcher/fr24/mission_classification.py`
- **Conflict:** the older module-boundary revision permits evidence-gated
  speculative mission classification, whereas active ontology v2.1 states that
  mission or intent inference of any kind remains prohibited.
- **Adjudication for this map:** active ontology v2.1 has higher current
  governance authority. Mission classification is compatibility/quarantine,
  not canonical FPIM evidence.
- **Migration gate:** `NO_MISSION_PROMOTION`.
- **Closure condition:** explicit later governance amendment or removal of the
  contradictory active compatibility behavior.

## Arithmetic

```text
contradictions = 2
OPEN           = 2
RESOLVED       = 0
SUPERSEDED     = 0
```

Contradictions remain visible; neither is silently normalized away.
