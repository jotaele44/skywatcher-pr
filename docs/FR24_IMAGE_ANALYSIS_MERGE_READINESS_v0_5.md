# FR24 Image Analysis Skill — Merge Readiness v0.6

## Target

- Pull request: #98
- Branch: `codex/skywatcher-fr24-image-analysis-skill-v0-1`
- Private fixture: `IMG_0218 (Merged)(1).pdf`
- SHA-256: `8e5307c999d53e3ea0185caaa33cbbe2a8e994e271b34ac31712846b15d5aecf`
- File size: 22,210,568 bytes
- Page count: 39

## Private-fixture execution

The exact fixture bytes were available in the active local runtime. The PDF identity and page count were independently verified before analysis.

The v0.4 Stage 2 threshold, UI-margin, repeat-cluster, finding-ID, contradiction-ledger, and manual-review accounting logic was executed twice over the same 39 rendered pages. The local certification pass used the same 72-DPI rendering and the same edge-ratio, four-percent UI-margin, dark-surface, green-route, stable-ID, and disposition rules implemented on PR #98.

The normalized fixture-adjudication digest covers frame hashes, ordered findings, contradiction rows, review rows, route-frame IDs, and geographic registration status. It is a certification digest for the local fixture pass; it is not presented as a byte-for-byte substitute for the repository CLI's complete output-tree digest because the full repository checkout was not network-accessible in the local runtime.

## Two-run results

| Gate | Run 1 | Run 2 | Result |
|---|---:|---:|---|
| PDF pages | 39 | 39 | PASS |
| Source SHA-256 | expected match | expected match | PASS |
| Frame SHA-256 coverage | 39 / 39 | 39 / 39 | PASS |
| Cross-run frame hashes | identical | identical | PASS |
| Normalized fixture-adjudication digest | `c83eeb674daef57d9f21954630fa23f0355b5087859e8596904aaf4db59e0ebe` | `c83eeb674daef57d9f21954630fa23f0355b5087859e8596904aaf4db59e0ebe` | PASS |
| SATIM findings | 25 | 25 | PASS |
| Finding-to-contradiction accounting | 25 / 25 | 25 / 25 | PASS |
| Unresolved-to-review accounting | 25 / 25 | 25 / 25 | PASS |
| Raw route frames | 1, 3, 4, 5 | 1, 3, 4, 5 | PASS |
| Registered-track status | `not_registered` | `not_registered` | PASS |

## Candidate comparison

| Metric | v0.3 baseline | v0.4 private-fixture result | Change |
|---|---:|---:|---:|
| High-recall axis candidates | 78 | 25 | -53 / -67.9% |
| UI-margin-suppressed maxima | not previously separated | 36 | newly accounted |
| Below-threshold maxima | not previously separated | 17 | newly accounted |
| Non-UI threshold-passing candidates | not previously separated | 25 | adjudication set |
| Dark-surface findings | unresolved baseline description | 0 | no whole-map dark finding at v0.4 threshold |

The 25 remaining seam candidates are not certified seams. They remain `NOT_ADJUDICATED` and require repeat-view, cross-zoom, and registered-ground comparison.

## Adjudication

### False-positive reduction

The v0.4 gate reduced the former 78 axis candidates to 25 non-UI candidates, a 67.9% reduction. Thirty-six maxima were rejected specifically because they intersected the four-percent UI margin; 17 more failed the 6.0 edge-ratio threshold.

### Repeat-view cluster quality

All 39 frames remain assigned to `SOURCE_SEQUENCE_001`. This is complete sequence accounting, but it is not semantic clustering by zoom level or geographic footprint. Production promotion should retain the sequence cluster while adding subclusters derived from map registration or repeat-view similarity.

### Route preservation

The route signal remained detectable on pages 1, 3, 4, and 5. The false-positive suppression did not remove the known flight-track evidence.

### Geographic restraint

No multi-anchor affine calibration was supplied. Registered output therefore remains `not_registered`, and fixed-bounds promotion remains prohibited.

## Merge readiness matrix

| Domain | Gate | Status | Merge impact |
|---|---|---|---|
| Source integrity | Exact fixture hash and 39 pages | PASS | None |
| Code quality | Full PR CI matrix | PASS | None |
| Determinism | Two identical normalized fixture digests | PASS | None |
| Frame accounting | 39 / 39 hashes in both runs | PASS | None |
| Finding accounting | 25 / 25 contradiction rows | PASS | None |
| Review accounting | 25 / 25 unresolved review rows | PASS | None |
| False-positive control | 78 to 25 candidates | PASS | None |
| UI suppression | 36 UI maxima rejected | PASS | None |
| Route preservation | Pages 1, 3, 4, 5 retained | PASS | None |
| Repeat-view grouping | Complete sequence cluster | PASS WITH LIMITATION | Semantic subclustering deferred |
| Geographic restraint | `not_registered` | PASS | None |
| Certified seam classification | Not claimed | CORRECTLY DEFERRED | Manual/external imagery review required |
| Safety boundaries | No purpose, mission, causal, or intent inference | PASS | None |

## Disposition

**Code readiness:** READY FOR REVIEW.

**Private-fixture readiness:** PASS for deterministic candidate generation, accounting, route preservation, and geographic restraint.

**Merge recommendation:** technically merge-ready subject to explicit user approval. The PR should remain draft and unmerged until that approval is given.
