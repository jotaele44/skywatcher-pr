# FR24 Image Analysis Skill — Certification v0.3

## Target

- Pull request: #98
- Branch: `codex/skywatcher-fr24-image-analysis-skill-v0-1`
- Functional hardening commit: `629ed228b64a689bf7f3fd1cb049e8f5369b7da4`
- Final tested head: `12d15e29cdf988a5fcc6d0c6185389bbc072bcdd`
- Fixture: operator-local `IMG_0218 (Merged)(1).pdf`
- Fixture media committed: no

## GitHub Actions

All required workflows passed on the final tested head:

- Federation template drift, run 54: success
- SATIM Runtime Smoke Tests, run 86: success
- Skywatcher CI, run 429: success
- Python test matrix: 3.10, 3.11, 3.12
- Imagery test matrix: 3.11, 3.12

The earlier hardening head failed the standard Python matrix because the orchestration fallback implicitly required imagery dependencies. Commit `629ed228...` removed that hidden dependency by adding Pillow-only route and artifact fallbacks while retaining repository-native adapters when available. The final test increment additionally verifies adapter provenance in both `ADAPTER_PROVENANCE.json` and `RUN_MANIFEST.json`.

## Typed integration and provenance

The orchestrator records `ADAPTER_PROVENANCE.json` and embeds the typed capability report in `RUN_MANIFEST.json`. Eight capabilities are accounted:

1. UI segmentation
2. Region OCR
3. RLSM OCR
4. Flight fusion
5. Track vectorization
6. Affine georegistration
7. SATIM engine
8. Tile-seam classification

Unavailable interfaces remain explicit degraded states. They do not generate synthetic flight facts, coordinates, purposes, missions, or intent.

## Fixture rerun

The 39-page fixture was rendered twice with the same pinned command used by the repository adapter:

```bash
pdftoppm -png -r 72 INPUT.pdf OUTPUT_PREFIX
```

The current dependency-safe Pillow route and edge-classification logic was applied identically to both rendered sets.

| Gate | Result |
|---|---:|
| Source SHA-256 | `8e5307c999d53e3ea0185caaa33cbbe2a8e994e271b34ac31712846b15d5aecf` |
| PDF pages, run 1 | 39 / 39 |
| PDF pages, run 2 | 39 / 39 |
| Source accounting | 100% |
| Frame SHA-256 coverage | 100% |
| Cross-run frame hashes | Identical |
| Normalized analysis digest, run 1 | `98b553a670e80135223b9ce2cdece3671433aaae503df8bc62baa30657a0b70b` |
| Normalized analysis digest, run 2 | `98b553a670e80135223b9ce2cdece3671433aaae503df8bc62baa30657a0b70b` |
| Deterministic rerun | Match |
| Flight-wave frame accounting | 39 |
| OCR ledger expectation | Nonempty when Tesseract is installed; explicit dependency-unavailable row otherwise |
| Green route pages | 1, 3, 4, 5 |
| Raw track feature expectation | At least one |
| Registered track | `not_registered` |
| Fixed-bounds promotion | false |
| Device/replay times | Separate fields |

## SATIM candidate disposition

The dependency-safe high-recall edge pass emitted 78 axis candidates, two per page. These are **not certified tile seams**. The result demonstrates deterministic candidate generation and repeat-view grouping, but also shows that the present single-maximum-per-axis heuristic is over-inclusive because strong UI, terrain, road, shadow, and image boundaries can dominate each axis.

Required production interpretation remains:

- candidate only;
- repeat-view adjudication required;
- no facility-purpose inference;
- no causal or flight-intent inference;
- no geographic promotion without multi-anchor calibration and residual/error reporting.

## Gate disposition

| Gate | Status |
|---|---|
| All required CI workflows successful | PASS |
| Identical normalized fixture digest | PASS |
| 39-page and frame-hash accounting | PASS |
| Raw route signal present | PASS |
| Registered track withheld absent calibration | PASS |
| SATIM candidates grouped for repeat review | PASS |
| Adapter provenance recorded and tested | PASS |
| Contradiction-ledger row accounting for every SATIM candidate | NOT YET CERTIFIED |
| Certified seam classification | NOT CLAIMED |

The contradiction ledger exists, but this certification does not claim 100% row-level disposition for all 78 candidates. That requires a follow-up patch linking each SATIM finding ID to an explicit `not_adjudicated`, `supported`, `contradicted`, or `duplicate` ledger row.

## Disposition

PR #98 remains open, draft, and unmerged. Merge is not authorized by this report.
