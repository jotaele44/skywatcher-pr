# Flight Corpus V4 family provenance

This document records methodology lineage only. Cluster labels are discovery identifiers, not aircraft, mission, operator, or route identities.

## Lineage

V2/V3 used DBSCAN-style recurrent-geometry discovery. V3 sensitivity testing showed that four consensus families were vulnerable to density chaining.

V4 therefore adjudicated those four families using pairwise/complete-link closure. The prior broad family manifestations remain historical observations and are **SUPERSEDED as canonical family boundaries**, not erased or declared false.

| V3 family | V3 tracks | V4 conservative subfamilies | Largest V4 subfamily | V4 state |
|---|---:|---:|---:|---|
| 1 | 122 | 5 | 61 | SUPERSEDED_BOUNDARY |
| 2 | 29 | 2 | 25 | SUPERSEDED_BOUNDARY |
| 3 | 26 | 3 | 21 | SUPERSEDED_BOUNDARY |
| 4 | 17 | 3 | 10 | SUPERSEDED_BOUNDARY |

Canonical source member: `complete_link_family_split.csv`
SHA-256: `b85b3d5c326f150a1d2f851d517b4c7ede3d26f04426ac80470b5c08778a3a88`

Summary member: `complete_link_family_split_summary.csv`
SHA-256: `9a0887d4a69a07cebf31b5161f300b18221a042a73034308624aafc227bce209`

## Interpretation gates

- DBSCAN family ≠ canonical route identity.
- Conservative subfamily ≠ mission.
- Shared geometry ≠ shared purpose.
- Algorithmic determinism ≠ evidence of real-world identity.
- SUPERSEDED means a later bounded method replaced the earlier boundary for canonical use; it does not mean the earlier computation never occurred.
