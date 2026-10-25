# Screenshot-to-Master-Flight-Log Intake v0.1

Status: **IMPLEMENTED INITIAL VERTICAL SLICE / NOT CORPUS-CERTIFIED**  
Scope: operator-local runtime, authenticated batch upload, lossless source inventory, bounded PDF/ZIP expansion, RLSM zone OCR, provisional aircraft-field extraction, full callsign candidate discovery, review-only UI.

The Master Flight Log remains the corpus authority. Screenshots are observational evidence. This implementation never synthesizes a native track, flight ID, end point, gap statistic, KML manifestation, owner/operator identity, landing, mission, or canonical corpus row.

## Source and commit anchor

Freeze the exact feature-branch SHA used for each operator run, including the RLSM schema, extraction software, and gold sample manifest. A green unit test is not full screenshot certification. Never overwrite prior mutable source snapshots.

## Local setup

1. Install project dependencies including the FR24 extra and the **system** Tesseract executable. The project already lists PyMuPDF for bounded local PDF rendering and Pillow for image decoding. HEIC requires its registered optional decoder.
2. Set a strong per-installation environment secret: SKYWATCHER_SCREENSHOT_TOKEN. The router can alternatively use an existing PRII_WRITE_TOKEN. If neither is configured **every screenshot endpoint fails closed with HTTP 503**. Legacy unauthenticated local-network write behavior is not inherited.
3. Run the backend from the repository root using uvicorn; start the existing frontend. Open FR24 Intake → Screenshot Processor.
4. Enter the screenshot token into the dedicated in-memory browser field. No token enters a job record, generated manifest, URL, or frontend persistent storage.
5. Select source files; examine the explicit preprocessing settings; optionally enable append-only OCR reprocessing, perceptual-similarity discovery, rendered-track pixel analysis, or existing supported georeference reuse; execute. The persistent job database is under inputs/screenshots/runtime by default and is excluded from Git.
6. Expand individual extracted items and, when needed, request a lazy, authenticated, hash-verified preview of the original image manifestation. Review extraction fields and all discovered candidate links. Add review notes. This action **does not** certify flight identity or change canonical corpus rows.

Tests:

    pytest -q tests/test_screenshot_to_mfl_intake.py tests/test_screenshot_intake_api.py
    pytest -q tests/test_server_smoke.py

Browser build:

    cd frontend && npm run build

## Runtime contracts

- POST /api/screenshot-runs: authenticated bounded base64 JSON batch; default profile local OCR/exact duplicate reuse/external vision off.
- GET /api/screenshot-runs: latest 30 processing histories.
- GET /api/screenshot-runs/{job_id}: status, real completion denominator, terminal tallies.
- GET /api/screenshot-runs/{job_id}/results: raw source manifest, every item, all field candidates, all discovered corpus candidate links, contradictions.
- GET /api/screenshot-runs/{job_id}/items/{item_id}/image: authenticated, hash-verified lazy image preview; no-store response.
- POST /api/screenshot-runs/{job_id}/control: pause/resume/cancel.
- POST /api/screenshot-runs/{job_id}/review: append stage-level operator review note; cannot bind a canonical flight.

The frontend currently polls job progress. Durable SQLite checkpoints survive server restarts; a new process requeues interrupted RUNNING items while preserving already completed items. Duplicate source hashes reuse RLSM OCR when the existing observation was marked complete unless the explicit reprocess-existing option requests a new append-only OCR attempt. PDF render scale affects only the derived manifestation; the original PDF SHA remains unchanged. New physical paths still receive distinct source manifestations.

## Bounded security

- 32 outer files per request; 32 MiB maximum per source; 40 MiB decoded batch; 58 MiB HTTP request cap.
- 300 ZIP file members; 80 MiB expanded-member budget; ratio threshold 100; explicit rejection for symlinks, encrypted members, nested ZIPs, unreadable or unsupported members. Member paths are stored as provenance, never used to construct output paths.
- 60 PDF pages, with one independently hashed rendered PNG manifestation per successfully rendered page; zero-page, malformed, encrypted, oversize, and missing-renderer outcomes remain BLOCKED.
- Screenshots are stored beneath an operator-local non-versioned runtime directory; no source screenshots or case-specific hashes are committed to the public repository.
- The browser token is in React state only. HTTPS or genuinely local-only binding is required outside a trusted local host.
- Untrusted multi-user uploads require an additional sandboxed decoder worker, rate limits, request quotas, and host-level resource isolation before exposure.

## Identity and temporal restrictions

- Preserve RAW screenshot label, member path, source SHA-256, page, derived image SHA-256, and RLSM screenshot id separately.
- Registration is a provisional observation, not an airframe, operator, or flight binding.
- Exact displayed source-flight-ID and callsign discovery against flight_corpus_records retains the **entire union** of matching records and the match basis for each record; no best-one heuristic or arbitrary nearest match.
- Present height/speed observations are not whole-flight maxima. A screenshot trail is not timestamped raw trajectory geometry.
- Tied or contradictory registration strings remain UNRESOLVED and do not produce a selected registration.
- Empty OCR cannot generate a successful extraction result.
- Manual review marks a staged item REVIEWED, **not** a canonical identity.

## Current deliverables and bounded gates

| Gate | Status | Evidence |
|---|---|---|
| Batch byte/manifest accounting | CODED; TEST REQUIRED | Frozen sources, item states, sizes and SHA |
| Exact duplicate provenance | CODED; TEST REQUIRED | RLSM screenshot + source manifestations |
| Authoritative corpus no-write | CODED; TEST REQUIRED | Read-only callsign candidate discovery |
| Restart/pause/cancel | CODED; TEST REQUIRED | SQLite job statuses and saved items |
| Authentication | CODED; TEST REQUIRED | Explicit token on all routes |
| RLSM OCR stage | INTEGRATED; OPERATOR TEST OPEN | Local Tesseract and operator media required |
| Gold 300 independent sample | BLOCKED | Operator-local annotations not supplied |
| 98% gold label recall threshold | BLOCKED | Must be measured, never assumed |
| Independent aircraft-field accuracy | OPEN | Build labeled benchmark |
| Perceptual similarity discovery | CODED; TEST REQUIRED | Complete local pHash neighborhood; never identity/dedup promotion |
| Perceptual dedup promotion | BLOCKED | Requires independent false-positive benchmark and review policy |
| Vision second opinion | OPEN | Provider-neutral existing adapter requires gated invocation |
| Displayed source-flight-ID discovery | CODED; TEST REQUIRED | Exact text match, full candidate union, still CANDIDATE_NOT_IDENTITY |
| Cross-frame flight ID adjudication | OPEN | Independent temporal truth and reviewed continuity required |
| Canonical MFL commit | NOT ENABLED | Schema-compatible append-only binding plus required independent evidence gate |
| Rendered-track pixel observation | CODED; TEST REQUIRED | Explicit RENDERED_TRAIL, raw_trajectory=false |
| Existing supported georeference reuse | CODED; TEST REQUIRED | Reads persisted RLSM receipts; does not synthesize transforms |
| Geo/SATIM/FPIM/CORRIM auto-chain | OPEN | Separate spatial + fusion certification required |
| Arbitrary Internet-facing upload | BLOCKED | Dedicated sandbox/resource isolation required |

## Follow-on execution order

1. Execute Python regression suite and frontend build against frozen feature-branch SHA; repair any failures.
2. Execute the bounded operator-local positive and negative screenshot packet.
3. Run the existing independently annotated 300-frame gold certification; record exact denominator and every unresolved frame.
4. Add optional cost-gated vision on the OCR-low-confidence slice, preserving model/run receipts, original zone OCR, and contradictions.
5. Benchmark perceptual-similarity false positives before considering any dedup promotion; preserve discovery-only status until then.
6. Validate rendered-track and persisted-georeference receipts on operator fixtures, then define their handoff contract without duplicating Spiderweb geometry authority.
7. Add independent temporal binding and cross-frame linkage on top of the displayed source-ID/callsign candidate union; preserve ties and contradictory clocks.
8. Implement authorized append-only corpus evidence links, field-level contradictions and compensated two-store persistence only after the promotion contract closes.
9. Connect certified SATIM/FPIM/CORRIM consumers through published evidence contracts.
10. Re-run regression and corpus certification on the final release commit; freeze hashes and manifests.

FOIA or external evidence requests are neither required nor initiated by this local intake feature.


## Operator-local certification surface

The FR24 Intake Screenshot Processor now includes a Certification tab protected by the same dedicated bearer-token boundary as screenshot intake.

It provides:

- local Tesseract / Python dependency / RLSM DB / corpus readiness;
- deterministic 300-frame gold-template generation;
- explicit unreviewed template state;
- authenticated JSON/JSONL gold upload;
- schema validation;
- exact 300-row denominator enforcement;
- duplicate resolved-frame rejection;
- explicit label annotation requirement, including reviewed `[]`;
- distinct annotator / reviewer enforcement;
- execution of the existing RLSM v2 audit;
- full required-gate display;
- frozen gold, database, logical corpus-manifest and output hashes;
- idempotent receipt reuse for identical frozen inputs;
- fail-closed `UNRESOLVED` state on audit-time input drift.

This closes the terminal-only operational gap but does not manufacture the missing operator-local annotations. Repository CI can certify the controller and audit logic; only an actual independently reviewed 300-frame local file can close the corpus certification gate.
