# Screenshot Intelligence Audit v0.1

This document defines the fail-closed extraction and certification boundary for the RLSM screenshot corpus.

## Operator-smoke findings

The first bounded operator run exposed stale source rows, incorrect failed-batch OCR completion semantics, divergent database routing, saturated standalone icon output, and empty-cluster failure handling. The first repair established explicit source reconciliation and one-database routing.

The second bounded run demonstrated the repaired behavior through OCR and adjacent icon persistence:

- 13,321 historical screenshot ledger rows were preserved.
- 12,301 source images were present and active.
- 1,020 absent historical sources were marked `missing_source` rather than deleted.
- 13 stale `in_progress` processing runs in the restored historical database were closed as failed with accounting.
- ordinary pending OCR targets were zero after reconciliation.
- all 21 word-box backfill targets completed successfully.
- aircraft extraction emitted and persisted 182 rows without counter divergence.
- label extraction emitted and persisted 878 rows without counter divergence.
- adjacent icon extraction emitted and persisted 842 rows without counter divergence.

The remaining stop occurred in the recurrence-gated standalone icon channel. Every one of the 200 frames exhausted the initial 24-candidate budget. The initial v2 implementation represented budget exhaustion as a failed scan and discarded the bounded candidate set before reporting `raw_candidates`, producing the apparently contradictory result `failed=200` and `raw_candidates=0`.

The corrected policy is:

- genuine read, decode, database, and runtime errors remain `failed`;
- bounded candidate-budget exhaustion is `truncated`, not a false processing failure;
- truncated scans retain a deterministic ranked representative set;
- map candidates require chroma and reject tile-border components;
- GUI candidates may be monochrome but require strong tonal separation;
- recurrence keys include visual hash, hue, geometry, fill, and region class;
- truncation counts and errors are emitted in the stage result and status output;
- bounded pipeline runs materialize crops for every currently persisted icon rather than applying a second icon-row cap.

## Required certification gates

1. 100% active screenshot accounting.
2. Zero silent failures.
3. 100% frame accounting.
4. 100% GUI-frame coverage.
5. 100% track receipt accounting.
6. 100% standalone-icon scan accounting.
7. Complete icon artifact capture.
8. No unsupported geolocation values.
9. 100% field-level provenance for non-null core fields.
10. Location-label recall of at least 98% on an independently reviewed 300-frame gold sample.

## Validation boundary

Repository CI validates code, schemas, deterministic exports, synthetic fixtures, and operator-regression cases. Full corpus certification remains blocked until a complete operator-local corpus run and an independently reviewed `data/rlsm/gold_sample_300.jsonl` are available. Missing gold data is never promoted to a pass.

## Preserved constraints

- Raw screenshots and original hashes are immutable inputs.
- Missing historical source rows remain in the ledger.
- Pixel observations remain separate from inferred associations.
- Standalone icons remain provisional and require review.
- Geographic coordinates remain null without supported calibration.
- PR #161 remains draft and unmerged until all required gates are satisfied.
