# FR24 Image Analysis Skill — Certification v0.3, amended by v0.4

## Target

- Pull request: #98
- Branch: `codex/skywatcher-fr24-image-analysis-skill-v0-1`
- v0.4 functional head: `bf2dc63e06d63d75317c86a31d2eefced8043f4d`
- v0.4 tested head: `548ca062d4c3a4b832d1b41515dbf5d645409901`
- Fixture: operator-local `IMG_0218 (Merged)(1).pdf`
- Fixture media committed: no

## GitHub Actions

All required workflows passed on the v0.4 tested head:

- Federation template drift, run 60: success
- SATIM Runtime Smoke Tests, run 89: success
- Skywatcher CI, run 432: success
- Python test matrix: 3.10, 3.11, 3.12
- Imagery test matrix: 3.11, 3.12

## v0.4 accounting closure

The Stage 2 exporter now assigns stable `SATIM-######` identifiers before writing either GeoJSON or CSV. Every exported SATIM finding receives exactly one row in `CONTRADICTION_LEDGER.csv`. Every finding with status `candidate` or `unresolved` receives exactly one row in `MANUAL_REVIEW_QUEUE.csv`.

Allowed dispositions are:

- `NOT_ADJUDICATED`
- `SUPPORTED`
- `CONTRADICTED`
- `DUPLICATE`
- `FALSE_POSITIVE`
- `NOT_APPLICABLE`

The run validator rejects packages where:

- SATIM finding count differs from contradiction-ledger row count; or
- unresolved/candidate count differs from manual-review row count.

Zero-finding runs remain valid and produce header-only accounting ledgers.

## v0.4 seam false-positive gate

The previous mandatory maximum vertical and horizontal edge emission was removed. A possible seam is now emitted only when:

1. the maximum edge score is at least `6.0` times the mean axis score;
2. the candidate does not intersect the configured four-percent UI margin; and
3. the frame has sufficient dimensions for analysis.

Each Stage 2 finding now records:

- `repeat_view_cluster_id`
- `screen_alignment_score`
- `ground_alignment_status`
- `cross_zoom_persistence`
- `ui_overlay_intersection`

The default repeat-view cluster remains `SOURCE_SEQUENCE_001`; persistence and ground alignment remain `NOT_ADJUDICATED` until a later analyst or registered-image comparison resolves them.

## Typed integration and provenance

The orchestrator records `ADAPTER_PROVENANCE.json` and embeds the same typed report in `RUN_MANIFEST.json`. Eight capability families remain fully accounted:

1. UI segmentation
2. Region OCR
3. RLSM OCR
4. Flight fusion
5. Track vectorization
6. Affine georegistration
7. SATIM engine
8. Tile-seam classification

Unavailable interfaces remain explicit degraded states and do not generate synthetic flight facts, coordinates, purposes, missions, or intent.

## Fixture baseline

The last operator-local fixture execution before the v0.4 threshold change established:

| Gate | Result |
|---|---:|
| Source SHA-256 | `8e5307c999d53e3ea0185caaa33cbbe2a8e994e271b34ac31712846b15d5aecf` |
| PDF pages | 39 / 39 |
| Source accounting | 100% |
| Frame SHA-256 coverage | 100% |
| Cross-run frame hashes | Identical |
| Deterministic rerun | Match |
| Flight-wave frame accounting | 39 |
| Green route pages | 1, 3, 4, 5 |
| Registered track | `not_registered` |
| Fixed-bounds promotion | false |
| Device/replay times | Separate fields |

The 39-page private fixture was not available inside the GitHub Actions runtime. Therefore, this amendment does not claim a new post-v0.4 fixture candidate count or normalized fixture digest. The changed threshold is covered by synthetic zero-finding, single-finding, multi-frame, UI-boundary, and deterministic-order tests.

## Test coverage added

- zero-finding accounting case;
- one finding mapped to one contradiction and one review row;
- UI-edge suppression;
- multi-frame repeat cluster assignment;
- deterministic finding-ledger order;
- complete disposition vocabulary;
- validation-time 100% accounting gates.

## Gate disposition

| Gate | Status |
|---|---|
| All required CI workflows successful | PASS |
| Stable finding IDs assigned before export | PASS |
| Finding-to-contradiction accounting | PASS by implementation and tests |
| Unresolved-to-review accounting | PASS by implementation and tests |
| Zero-finding ledger case | PASS |
| UI-boundary false-positive suppression | PASS |
| Mandatory one-axis-candidate behavior removed | PASS |
| Repeat-view metadata fields | PASS |
| Deterministic ledger ordering | PASS |
| Registered track withheld absent calibration | PASS |
| Facility-purpose and flight-intent inference prohibited | PASS |
| Post-v0.4 39-page fixture rerun | NOT EXECUTED IN GITHUB RUNTIME |
| Certified seam classification | NOT CLAIMED |

## Disposition

The structural contradiction-accounting and seam false-positive gates are closed. PR #98 remains open, draft, and unmerged. Merge is not authorized by this report.
