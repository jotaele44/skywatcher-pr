# FR24 Image Analysis Skill — Certification v0.3, amended through v0.6

## Target

- Pull request: #98
- Branch: `codex/skywatcher-fr24-image-analysis-skill-v0-1`
- v0.4 tested head: `548ca062d4c3a4b832d1b41515dbf5d645409901`
- Private fixture: `IMG_0218 (Merged)(1).pdf`
- Fixture SHA-256: `8e5307c999d53e3ea0185caaa33cbbe2a8e994e271b34ac31712846b15d5aecf`
- Fixture pages: 39
- Fixture media committed: no

## GitHub Actions

All required workflows passed on the v0.4 tested head:

- Federation template drift, run 60: success
- SATIM Runtime Smoke Tests, run 89: success
- Skywatcher CI, run 432: success
- Python test matrix: 3.10, 3.11, 3.12
- Imagery test matrix: 3.11, 3.12

## v0.4 accounting and seam gate

The Stage 2 exporter assigns stable `SATIM-######` identifiers before writing GeoJSON or CSV. Every finding receives one contradiction-ledger row, and every `candidate` or `unresolved` finding receives one manual-review row.

Allowed dispositions are `NOT_ADJUDICATED`, `SUPPORTED`, `CONTRADICTED`, `DUPLICATE`, `FALSE_POSITIVE`, and `NOT_APPLICABLE`.

A possible seam is emitted only when the maximum axis edge score is at least 6.0 times the mean axis score and the candidate does not intersect the four-percent UI margin. Each finding records repeat-view cluster, screen-alignment score, ground-alignment status, cross-zoom persistence, and UI-overlay intersection.

## v0.6 private-fixture certification

The exact 39-page fixture bytes were available in the active local runtime. Source hash and page count were verified before analysis. The v0.4 rendering, detector, accounting, and safety rules were applied twice.

| Gate | Result |
|---|---:|
| Source SHA-256 | match |
| PDF pages | 39 / 39 |
| Frame hash coverage | 39 / 39 in both runs |
| Cross-run frame hashes | identical |
| Normalized fixture-adjudication digest, run 1 | `c83eeb674daef57d9f21954630fa23f0355b5087859e8596904aaf4db59e0ebe` |
| Normalized fixture-adjudication digest, run 2 | `c83eeb674daef57d9f21954630fa23f0355b5087859e8596904aaf4db59e0ebe` |
| SATIM findings | 25 |
| Contradiction accounting | 25 / 25 |
| Manual-review accounting | 25 / 25 |
| Route frames | 1, 3, 4, 5 |
| Registered-track status | `not_registered` |
| Dark-surface findings | 0 |

The normalized digest covers ordered frame hashes, finding rows, contradiction rows, review rows, route-frame IDs, and registration status. It is a local fixture-certification digest rather than a claim that the entire repository CLI output tree was reproduced byte-for-byte in a network-isolated runtime.

## v0.3 versus v0.4 comparison

| Metric | v0.3 | v0.4 | Change |
|---|---:|---:|---:|
| Axis candidates | 78 | 25 | -53 / -67.9% |
| UI-suppressed maxima | not separated | 36 | explicit suppression |
| Below-threshold maxima | not separated | 17 | explicit suppression |
| Non-UI threshold-passing candidates | not separated | 25 | retained review set |

No remaining candidate is certified as a tile seam. All remain `NOT_ADJUDICATED` pending repeat-view, cross-zoom, and independent imagery review.

## Adjudication

- False-positive reduction: PASS. Candidate volume fell 67.9%.
- Route preservation: PASS. Pages 1, 3, 4, and 5 remain detected.
- Finding-to-contradiction accounting: PASS at 100%.
- Unresolved-to-review accounting: PASS at 100%.
- Repeat-view grouping: PASS for complete sequence accounting; semantic subclustering remains deferred.
- Geographic restraint: PASS. No affine fit means no registered geographic track.
- Facility-purpose and flight-intent inference: prohibited and not generated.

## Final disposition

The code, CI, accounting, deterministic private-fixture pass, route preservation, and geographic-restraint gates are complete.

PR #98 is technically ready for explicit merge adjudication. It remains draft and unmerged until the user separately authorizes merge.
