# Screenshot Processor → Master Flight Log Integration

Status: **IMPLEMENTED / PROVISIONAL UNTIL CI + OPERATOR RUNTIME VALIDATION**

## Purpose

The Screenshot Processor adds an interactive, local-first intake path to Skywatcher's existing FR24/RLSM stack. It accepts screenshots, ZIP archives, and PDFs; freezes source identity; expands visual manifestations without collapsing duplicate paths; runs bounded local extraction; generates reviewable Master Flight Log candidate links; and preserves the existing canonical flight corpus as the authority.

It does **not** promote screenshot observations into canonical flight identity automatically.

## User workflow

1. Open **FR24 Intake → Screenshot Processor**.
2. Upload one or more screenshots, PDFs, or ZIP archives.
3. Configure preprocessing:
   - source family;
   - local OCR;
   - optional vision-assist intent;
   - rendered-track vectorization;
   - use of existing georeference evidence;
   - Master Flight Log reconciliation;
   - candidate time-window metadata.
4. Press **Execute Processing**.
5. Follow durable job progress through:
   - inventory;
   - OCR;
   - field extraction;
   - rendered-track observation;
   - reconciliation;
   - finalization.
6. Inspect extracted fields and full candidate sets.
7. Add an explicit review rationale to any candidate selected for persistence.
8. Press **Commit reviewed candidate links**.

The commit step persists a screenshot manifestation with
`binding_status='candidate'`. It does not change
`flight_corpus_records.identity_status` and does not write
`analytical_flight_id`.

## Source/container denominator

The processor preserves two different grains:

- source upload: the exact user-supplied file;
- processable visual manifestation: a native image, an image member within a ZIP, or a rendered PDF page.

A ZIP archive may therefore produce N processable manifestations plus excluded non-image members. Duplicate image bytes at different member paths are retained as separate source manifestations.

For PDFs, each rendered page is explicitly marked as a distinct manifestation from the PDF's byte identity.

## Runtime storage

Runtime-only files are written beneath:

`data/screenshot_processing/jobs/<job-id>/`

The durable processing ledger is:

`data/screenshot_processing/jobs.sqlite3`

These are runtime artifacts, not repository source artifacts.

The RLSM screenshot database remains:

`data/rlsm/rlsm_screenshot_analysis.sqlite`

The canonical flight corpus remains in the configured Skywatcher database
(`SKYWATCHER_DB`, otherwise `data/skywatcher.db`).

## Identity and matching rules

The processor obeys the flight-corpus entity separation:

`AIRFRAME | REGISTRATION | CALLSIGN | FLIGHT_ID | SOURCE_FOLDER | OWNER | OPERATOR | MISSION`

Candidate generation currently uses exact callsign agreement when available. It does not treat registration as callsign and does not infer airframe identity from a callsign.

Every generated relationship is:

`CANDIDATE_NOT_IDENTITY`

Tied or multiple candidate matches remain unresolved. Full candidate sets are preserved.

No candidate selection is silently promoted to `bound`.

## Screenshot field extraction

Local OCR reuses the RLSM OCR implementation and raw OCR remains append-only.

Structured aircraft extraction reuses the existing RLSM field parser. Typical extracted observations include:

- registration;
- callsign when independently visible;
- aircraft type;
- altitude;
- speed;
- heading;
- operator text.

These values are provisional screenshot observations.

A rendered FR24 track may be vectorized through the existing track-vectorizer. Its evidence type is explicitly recorded as:

`RENDERED_TRAIL`

and:

`raw_trajectory=false`

A rendered trail therefore never becomes a native telemetry trajectory.

## Georeference handling

The interactive processor consumes already-persisted supported RLSM georeference evidence when it exists.

It does not synthesize coordinates from nearest labels, map prominence, or unsupported one-off guesses.

When no supported transform exists, georeference remains unresolved.

## Vision assistance

The UI records an operator's desired vision-assist policy, but the local processor does not silently invoke an external model.

Provider-neutral vision results can already be ingested through the existing
`aviation_vision_extraction.v1` contract. Until a governed model-execution adapter is explicitly configured, a requested vision-assist stage is reported as **BLOCKED**, while local OCR results remain usable.

This prevents an API call or source-image upload from occurring merely because a default setting exists.

## Security

Screenshot-processing API routes use a stricter access guard than generic dashboard writes.

When `PRII_WRITE_TOKEN` is configured, it is required.

When no token is configured, screenshot-processing routes are loopback-only by default.

Trusted private-network access requires explicit opt-in:

`SKYWATCHER_SCREENSHOT_ALLOW_PRIVATE_NETWORK=1`

Additional intake limits are controlled by:

- `SKYWATCHER_SCREENSHOT_SOURCE_MAX_BYTES`
- `SKYWATCHER_SCREENSHOT_JOB_MAX_BYTES`
- `SKYWATCHER_SCREENSHOT_MAX_ARCHIVE_MEMBERS`
- `SKYWATCHER_SCREENSHOT_MAX_ARCHIVE_BYTES`

Archive extraction is bounded by member count and expanded-byte limits.

## Persistence and idempotence

Exact screenshot payload SHA-256 values reuse the existing RLSM logical screenshot row.

Different source paths with the same payload remain separate RLSM source manifestations.

Master Flight Log candidate commits are idempotent on:

`corpus_record_id + source_kind='screenshot' + source_sha256`

Re-importing the same reviewed manifestation therefore does not multiply the canonical corpus.

## Failure and interruption behavior

Processing jobs are durable.

Supported control states are:

`STAGED | QUEUED | RUNNING | PAUSED | COMPLETED | FAILED | CANCELED`

The worker checks pause/cancel state between bounded work units.

A failed downstream stage does not delete already-persisted source identity, RLSM OCR, or earlier job receipts.

## UI surfaces

### Screenshot Processor

Upload, settings, execution controls, progress, results, candidate selection, and commit.

### Processing History

Persistent job list with stage, state, progress, source count, and review count.

### Review Queue

Preserves the pre-existing Skywatcher capture queue. It is not replaced by the new job ledger.

## API

- `GET /api/screenshot-processing/jobs`
- `POST /api/screenshot-processing/jobs`
- `GET /api/screenshot-processing/jobs/{job_id}`
- `POST /api/screenshot-processing/jobs/{job_id}/execute`
- `POST /api/screenshot-processing/jobs/{job_id}/pause`
- `POST /api/screenshot-processing/jobs/{job_id}/resume`
- `POST /api/screenshot-processing/jobs/{job_id}/cancel`
- `POST /api/screenshot-processing/jobs/{job_id}/commit`

## Certification gates

The feature must not be called CERTIFIED until all applicable gates close:

1. Python unit/regression suite PASS on all supported CI Python versions.
2. Ruff PASS.
3. Frontend lint PASS.
4. Frontend tests PASS.
5. Frontend production build PASS.
6. Source/member/page arithmetic closes for bounded fixtures.
7. Exact duplicate source paths remain preserved.
8. Reconciliation never modifies canonical identity status automatically.
9. Reviewed commits persist only candidate evidence.
10. Operator-local runtime smoke demonstrates actual OCR/progress/restart behavior.
11. Existing screenshot-intelligence certification gates remain applicable for corpus-wide extraction claims.

Repository CI proves code and fixture behavior only. It does not certify extraction accuracy over the operator-local screenshot corpus.
