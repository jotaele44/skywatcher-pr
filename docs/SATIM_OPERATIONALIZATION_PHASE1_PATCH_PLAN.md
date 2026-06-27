# SATIM Operationalization Phase 1 Patch Plan

## Active Vector

`SATIM_OPERATIONALIZATION_PHASE1`

## Scope

Target repository: `jotaele44/skywatcher-pr`

Branch: `feature/satim-operationalization-phase1`

This phase converts the existing SATIM scoring and calibration logic into an operational contract layer. It does not merge to `main` and does not replace the existing L5 classifiers.

## Deliverables

| Deliverable | Path | Purpose |
|---|---|---|
| SATIM visual ledger schema | `schemas/satim_visual_ledger.schema.json` | Canonical row contract for imagery-derived visual candidates. |
| Tile artifact ledger schema | `schemas/tile_artifact_ledger.schema.json` | Audit contract for tile seams, UI overlays, track overlays, mixed-epoch artifacts, and persistent ground features. |
| Candidate extraction stub | `fr24/calibration/satim_candidate_extraction.py` | Normalizes raw candidate metadata into the visual ledger contract. |
| Track/UI/tile rules | `docs/SATIM_TRACK_LINE_VS_TILE_SEAM_RULES.md` | Prevents FR24 route/UI artifacts from being promoted as imagery structure. |
| Mixed-epoch spec | `docs/SATIM_MIXED_EPOCH_VALIDATION_SPEC.md` | Defines the required multi-date validation gate. |
| Contract test stubs | `tests/test_satim_operationalization_phase1_contracts.py` | Verifies schemas load and candidate normalization produces required ledger fields. |

## Implementation Sequence

1. Add schemas.
2. Add candidate extraction contract stub.
3. Add decision-rule documents.
4. Add test stubs.
5. Run targeted tests.
6. Open draft PR or leave branch staged for review.

## Non-Goals

- No full raster edge detector in Phase 1.
- No automatic imagery provider download layer in Phase 1.
- No dashboard implementation in Phase 1.
- No promotion of one-still-image candidates to confirmed tile seam or structural signal.

## Gap Coverage

| Gap | Phase 1 Coverage |
|---|---|
| Automated candidate extraction | Stub + contract only. Full raster extraction deferred. |
| Multi-date / mixed-epoch validation | Spec + required ledger fields. Execution engine deferred. |
| Track-line vs tile-seam vs UI-overlay separation | Rule matrix and artifact classes added. |
| GIS overlay automation | Schema fields added for alignments; spatial joins deferred. |
| SATIM visual + artifact ledgers | Schemas added. |
| Review UI / dashboard | Deferred. |
| Expanded tests with real AOIs | Contract tests added; real fixtures deferred. |

## Validation Target

```bash
python -m pytest tests/test_satim_operationalization_phase1_contracts.py
```

## Merge Gate

Do not merge until:

- schemas are reviewed against downstream export needs;
- candidate extraction stub is accepted as the stable input contract;
- track/UI/tile suppression rules are aligned with FR24 screenshot processing;
- mixed-epoch spec is accepted as the promotion gate for imagery artifacts.
