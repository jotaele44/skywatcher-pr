# Skywatcher SATIM Integrated Test Run

Vector: `SKYWATCHER_SATIM_INTEGRATED_TEST_RUN`

Status: staged engine/test pipeline only. Do not merge to `main` until validation criteria are satisfied.

## Purpose

Build a repeatable pipeline that integrates:

1. aircraft flight-event logging;
2. SATIM visual review;
3. seam, tile, UI-overlay, zoom-blur, compression, and mixed-epoch artifact detection;
4. evidence-tiered output ledgers that can feed the wider Skywatcher workflow.

## Input contract

The engine must accept analyst-provided local files at runtime. Source images/screenshots are **not committed** to the repository and must not be hard-coded in docs, scripts, schemas, or ledgers.

Supported input extensions:

- `.pdf`
- `.jpg`
- `.jpeg`
- `.png`
- `.heic`
- `.heif`
- `.webp`
- `.tif`
- `.tiff`

Input files are ephemeral runtime artifacts. The repository stores only:

- schemas;
- scripts;
- generic test fixtures where needed;
- derived ledgers produced by the operator when intentionally exported;
- validation reports that reference input type and run ID, not the source filename unless the operator opts in outside the repo.

## Runtime manifest

Each run should be driven by a manifest rather than a hard-coded screenshot packet.

Minimum manifest fields:

| Field | Required | Notes |
|---|---:|---|
| `run_id` | yes | Operator-defined or generated unique run identifier |
| `input_path` | yes | Local runtime path; not committed |
| `source_family` | yes | Example: `fr24`, `adsbexchange`, `manual_map_review`, `unknown` |
| `source_app` | no | Optional app/platform label |
| `observed_timestamp` | no | Timestamp if visible or operator-provided |
| `aircraft_label` | no | Registration/callsign if visible |
| `geographic_context` | no | Free-text AOI context |
| `analyst_notes` | no | Non-evidentiary operator notes |

## Required outputs

| Output | Purpose |
|---|---|
| Flight event ledger | Normalized flight-event packet when aircraft context exists |
| SATIM visual ledger | Page/frame-level visual observations |
| Tile artifact ledger | Artifact-control rows |
| Schemas | Machine-readable contracts |
| Scripts | Reproducible runtime intake/classification |

## Classification model

| Class | Meaning | Minimum threshold |
|---|---|---|
| `TRACK_LINE` | Flight-app route/playback path, not map imagery | UI/route geometry visible across aircraft playback context |
| `TILE_SEAM` | Imagery boundary or tile compositing discontinuity | Linear/rectilinear boundary independent of flight route geometry |
| `UI_OVERLAY` | App interface or map label obstruction | Overlay text/icon/player panel visibly contaminates scene |
| `ZOOM_BLUR` | Resolution/scale artifact | Loss of detail after zoom; no stable geometry |
| `COMPRESSION` | Image/PDF compression artifact | Blockiness, haloing, smear, or export degradation |
| `MIXED_EPOCH` | Adjacent imagery from different acquisition periods | Tone/season/texture discontinuity across tile boundary |
| `SHADOW_CONFUSION` | Shadow/relief ambiguity | Vegetation, terrain, or structure shadow can explain form |
| `LABEL_COLLISION` | Map label collision | Label or icon overlaps target geometry |
| `STRUCTURAL_SIGNAL` | Potential physical feature after artifact exclusion | Recurrent geometry/access/clearing/structure evidence, with contradictions logged |

## Evidence rules

- Do not promote any visual anomaly directly to `STRUCTURAL_SIGNAL`.
- Unknown or weakly classified rows default to `HOLD_REVIEW`, not `STRUCTURAL_SIGNAL`.
- First classify artifact risk.
- Require page/frame reference, map context, observation type, confidence, contradiction, and blind spot.
- Keep aircraft-event evidence separate from visual-imagery evidence.
- Do not infer facility purpose from screenshots/images alone.

## Validation gates before merge

1. Runtime intake accepts generic image/PDF inputs through a manifest.
2. No committed file or doc depends on a specific uploaded screenshot packet.
3. `TRACK_LINE` versus `TILE_SEAM` is explicitly separated.
4. UI overlay, zoom blur, compression, and shadow confusion are logged as contamination risks.
5. Every `STRUCTURAL_SIGNAL` candidate includes contradiction and blind-spot fields.
6. CSV/JSONL outputs validate against schema.
7. No claim exceeds source visibility.

## Non-goals

- No source screenshots/images/PDFs committed to the repo.
- No FR24 security bypass.
- No automated scraping behind verification gates.
- No main-branch merge in this vector.
