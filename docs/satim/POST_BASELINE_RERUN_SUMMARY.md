# SATIM post-baseline rerun summary

## Baseline

- Engine baseline commit: `95ce71a56a2930dbd3f7d7fefd39246b591127e2`
- Baseline ref: `baseline/stable-graph-id-baseline`
- Input set: 6 source ZIPs

## Input ZIPs

- `Archive(52).zip`
- `Archive(53).zip`
- `Covert Helo(1).zip`
- `FR24_fetched.zip`
- `N79036 CSVs & KMLs.zip`
- `The Money Run(1).zip`

## Run summary

| Metric | Value |
|---|---:|
| Manifest files | 377 |
| Track files parsed | 52 |
| Track rows | 119307 |
| Graph nodes | 7783 |
| Graph edges | 7731 |
| Parser errors | 0 |
| Non-track CSV skipped | 112 |
| Visual OCR rows | 28 |
| Duplicate node IDs | 0 |
| Duplicate edge rows | 0 |

## Stability checks

| Check | Result |
|---|---|
| Repeat-run SHA match for track ledger, graph nodes, and graph edges | PASS |
| Batch-composition graph ID stability | PASS |
| Error ledger | PASS: empty |

## Frozen package hashes

- Report package SHA-256: `8eb2686d8fd7b161e9c97abc0170e9b243d910cb409180c1e421ae839282e8e6`
- Rerun report SHA-256: `b9d982e29c675ba36bdfb5809251448cc4721f31ae4f108cf60305c4b43e76de`

## Decision

`POST_BASELINE_RERUN_STATUS = PASS`
