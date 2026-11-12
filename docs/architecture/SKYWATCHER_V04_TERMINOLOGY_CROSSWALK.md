# Skywatcher v0.4 terminology crosswalk

**Status:** Draft, non-destructive internal compatibility adapter.

The governing source of truth is `docs/SKYWATCHER_EVIDENCE_INGESTION_CONTRACT.md`.
`src/skywatcher/core/terminology_crosswalk.py` preserves the original value and
returns a proposed normalized value only with an explicit status.

| Proposed glossary display term | Governing evidence hint | Status |
|---|---|---|
| OBSERVED | FACT | Requires review: direct observation must be established |
| DERIVED | COMPUTED | Requires review: reproducible calculation must be established |
| INFERRED | INFERENCE | Requires review: basis and uncertainty required |
| HYPOTHESIZED | HYPOTHESIS | Requires review: not a verified claim |
| VERIFIED | — | No automatic certification conversion |
| REJECTED | — | No automatic certification conversion |

The full governing certification enum remains unchanged. Exact canonical
values round-trip. Unsupported terms remain `UNRESOLVED`, not guessed.

## Existing ILAP interface collision

`src/skywatcher/corrim/ilap_airspace_bridge.py` currently exports flight
LineStrings under `airspace_ilap_candidates.geojson`, and generates POI
candidates from recurring aircraft tracks. Those are **airspace screening
outputs**, not certified terrestrial access points.

Do not reinterpret the existing GeoJSON filename or legacy records as
verified '(Potential) In-Land Access Points'. A future registry requires a
separate versioned schema, explicit ground evidence, independent provenance,
and publication safeguards. Existing scores are review heuristics, not proof
of a physical entrance or operational purpose.

## Integration gates

1. Preserve historical raw values and exact governing enums.
2. Require review before persisting proposed aliases.
3. Add separate ILAP terrestrial candidate type; do not migrate legacy flight
   corridor LineStrings into ground-access records by name.
4. Keep research priority, evidence level, infrastructure documentation,
   and SARP access/publication status as independent dimensions.
5. This adapter is **internal**, has no API, GUI control, or scheduled job;
   any user-facing rollout requires `AGENTS.md` GUI parity protocol.
6. Run `pytest tests/test_terminology_crosswalk.py`, existing ILAP/evidence
   regressions, and federation GUI parity gates before promotion.
