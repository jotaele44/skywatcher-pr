# Recapture list — 8 lost frames, 2026-03-03

Eight screenshots are inventoried in `rlsm_screenshot_analysis.sqlite` but absent
from disk. They are the only gap left in the corpus after the 2026-03 Takeout
export was normalized (that restored 1,011 of the original 1,020 orphans, plus
one more once Takeout's `(1)` duplicate naming was handled).

These eight were never in the export. Nothing is recoverable from the pipeline
side — the rows carry the metadata, the pixels are gone.

## What was being tracked

The wave ran 18:35:49 → 18:38:00 AST — 2 minutes 11 seconds, nine frames. **One
survived**: `2026-03-03T18-37-23_629afa85.png`, sitting between orphans #6 and
#7. OCR of its aircraft card reads:

```
N620GG  R44  Private owner  SIG
Robinson R44 Raven II   REG. N620GG
BAROMETRIC ALT. NOT AVAILABLE   GROUND SPEED 3 mph
Departed 00:31 ago
```

So the subject is **N620GG, a Robinson R44 Raven II**, privately owned, out of
**SIG — Fernando Luis Ribas Dominicci (TJIG), Isla Grande, San Juan**. Reading
`Departed 00:31 ago` as FR24's H:MM puts the departure near **18:06 AST**, which
makes this wave a shot at roughly T+30. Ground speed 3 mph means it was hovering
or maneuvering, not in cruise.

The map layer in the same frame resolves Dorado, Bayamón, Salinas and the
Atlantic — San Juan metro, consistent with a departure off Isla Grande.

Treat the registration as a single uncorroborated OCR read until a second frame
confirms it; `N620GG` is legible and the type line agrees with it, which is
reassuring but not proof.

## The eight

All 1170×2532 PNG, `ingest_status='ok'`, `ocr_status='pending'`. Local column is
America/Puerto_Rico (UTC−4, no DST). The 8-hex suffix is `sha256(content)[:8]`.

| # | sid | Local (AST) | UTC | Expected filename | Bytes |
|---|-----|-------------|-----|-------------------|-------|
| 1 | 10272 | 18:35:49 | 22:35:49Z | `2026-03-03T18-35-49_e32c8be8.png` | 2,584,028 |
| 2 | 10273 | 18:35:54 | 22:35:54Z | `2026-03-03T18-35-54_5b1af378.png` | 2,716,804 |
| 3 | 10274 | 18:36:15 | 22:36:15Z | `2026-03-03T18-36-15_26b8f61a.png` | 2,111,127 |
| 4 | 10275 | 18:36:28 | 22:36:28Z | `2026-03-03T18-36-28_9f670f4a.png` | 2,801,667 |
| 5 | 10276 | 18:36:44 | 22:36:44Z | `2026-03-03T18-36-44_c2ede089.png` | 3,046,848 |
| 6 | 10277 | 18:36:55 | 22:36:55Z | `2026-03-03T18-36-55_5e739d8e.png` | 2,833,681 |
| — | 10278 | 18:37:23 | 22:37:23Z | `2026-03-03T18-37-23_629afa85.png` | **on disk — the survivor** |
| 7 | 10279 | 18:37:34 | 22:37:34Z | `2026-03-03T18-37-34_108397a9.png` | 2,554,218 |
| 8 | 10280 | 18:38:00 | 22:38:00Z | `2026-03-03T18-38-00_c4074b5f.png` | 2,693,212 |

Bracketing frames on disk: `2026-03-03T14-58-26_69b42229.png` before,
`2026-03-04T17-31-30_e070ef88.png` after. Nothing else that evening.

## Recapturing

**The CSV track beats re-screenshotting.** You know the registration and a
two-minute window, so `scripts/fr24_harvest.py` can pull the timestamped
coordinates directly — exact positions instead of pixels an affine fit has to
infer. That also spends the 25/day quota on a flight that already has a
screenshot wave, which is what `docs/SCREENSHOT_DATA_STRATEGY.md` §6 asks for.

If you do want the frames, FR24 playback for **2026-03-03 22:35–22:38 UTC**
covers the whole wave, and the survivor tells you exactly what the map looked
like at 18:37:23 so you can match zoom and framing.

## One thing to decide

Recaptured screenshots are **new bytes** — different content, different
`sha256[:8]`, different filename. They will not resurrect rows 10272–10280;
inventory will add fresh rows alongside them, and these eight stay orphaned
forever.

So pick one:

- **Mark them.** `UPDATE screenshots SET ingest_status='unreadable' WHERE
  screenshot_id IN (10272,10273,10274,10275,10276,10277,10279,10280);` — records
  the loss honestly, and satisfies `test_failed_files_recorded`, which currently
  fails because nothing in the corpus is flagged.
- **Delete them.** Cleaner bijection, but the fact that a wave was lost
  disappears with the rows.

Marking is the better call: the gap is real, and a corpus that admits its holes
is worth more than one that looks complete.
