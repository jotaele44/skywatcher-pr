# Skywatcher SATIM Integrated Test Run

Vector: `SKYWATCHER_SATIM_INTEGRATED_TEST_RUN`

Status: staged test run only. Do not merge to `main` until validation criteria are satisfied.

## Purpose

Build a repeatable pipeline that integrates:

1. FR24 aircraft flight logging.
2. SATIM visual review.
3. Seam, tile, UI-overlay, zoom-blur, and mixed-epoch artifact detection.
4. Evidence-tiered output ledgers that can feed the wider Skywatcher workflow.

## Test input

Source packet: `IMG_6925.pdf`.

Observed context from packet:

- Source app: Flightradar24 over Apple Maps.
- Visible timestamp: Fri, Jun 26, 2026, 11:13 PM UTC -04:00.
- Visible aircraft label on page 1: `N407PR`.
- Geographic context: Puerto Rico, with islandwide overview plus Arecibo, San Sebastian, Lares, PR-370, forest/road/structure zoom frames.

## Required outputs

| Output | Path | Purpose |
|---|---|---|
| Flight event ledger | `data/test_runs/fr24_satim_2026-06-26_n407pr/flight_event_ledger.jsonl` | One normalized flight-event packet |
| SATIM visual ledger | `data/test_runs/fr24_satim_2026-06-26_n407pr/visual_review_ledger.csv` | Visual observations page by page |
| Tile artifact ledger | `data/test_runs/fr24_satim_2026-06-26_n407pr/tile_artifact_ledger.csv` | Artifact-control rows |
| Schemas | `schemas/*.schema.json` | Machine-readable contracts |
| Scripts | `scripts/ingest_fr24_screenshot_packet.py`, `scripts/classify_satim_artifacts.py` | Stubbed reproducible execution |

## Classification model

| Class | Meaning | Minimum threshold |
|---|---|---|
| `TRACK_LINE` | FR24 route/playback path, not map imagery | UI/route geometry visible across aircraft playback context |
| `TILE_SEAM` | Imagery boundary or tile compositing discontinuity | Linear/rectilinear boundary independent of flight route geometry |
| `UI_OVERLAY` | App interface or map label obstruction | Overlay text/icon/player panel visibly contaminates scene |
| `ZOOM_BLUR` | Resolution/scale artifact | Loss of detail after zoom; no stable geometry |
| `MIXED_EPOCH` | Adjacent imagery from different acquisition periods | Tone/season/texture discontinuity across tile boundary |
| `STRUCTURAL_SIGNAL` | Potential physical feature after artifact exclusion | Recurrent geometry/access/clearing/structure evidence, with contradictions logged |

## Evidence rules

- Do not promote any visual anomaly directly to structural signal.
- First classify artifact risk.
- Require page reference, map context, observation type, confidence, contradiction, and blind spot.
- Keep aircraft-event evidence separate from visual-imagery evidence.

## Validation gates before merge

1. PDF/screenshot intake produces stable row counts.
2. `TRACK_LINE` versus `TILE_SEAM` is explicitly separated.
3. UI overlay and zoom blur are logged as contamination risks.
4. Every `STRUCTURAL_SIGNAL` candidate includes contradiction and blind-spot fields.
5. CSV/JSONL outputs validate against schema.
6. No claim exceeds source visibility.

## Non-goals

- No FR24 security bypass.
- No automated scraping behind verification gates.
- No main-branch merge in this vector.
