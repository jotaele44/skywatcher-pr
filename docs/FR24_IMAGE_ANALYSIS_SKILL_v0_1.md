# FR24 Image Analysis Skill v0.1

## Architecture

The implementation is hybrid:

- `skills/skywatcher-fr24-image-analysis/` contains the installed-skill contract and JSON Schemas.
- `fr24_image_skill/` contains a repository-native deterministic orchestrator.
- Existing `fr24.*` and SATIM modules remain the analytical engines. The orchestrator invokes available command surfaces and records degraded states when an adapter cannot run.

## Stage boundary

Stage 1 inventories and hashes inputs and rendered frames, creates provenance-led flight products, preserves separate device/replay time fields, and prevents fixed-bounds geographic promotion. Its state is frozen before Stage 2 starts.

Stage 2 creates SATIM finding and repeat-view contracts. It executes only after Stage 1 is frozen and limits classifications to objective visual classes. Correlation runs only after both stages are frozen.

## Checkpointing and determinism

A stable run ID is derived from mode plus ordered source SHA-256 hashes. Inputs are processed lexicographically. PDF rendering is pinned to 150 DPI when `pdftoppm` is installed; video extraction is pinned to 1 FPS when `ffmpeg` is installed. Every run writes source and frame inventories, checksums, stage manifests, warning state, contradiction ledger, manual-review queue, and validation report.

## Degraded operation

Missing `pdftoppm`, `ffmpeg`, optional OCR/CV dependencies, or unsupported CLI surfaces must not generate synthetic observations. The run records warnings and emits empty, schema-valid candidate ledgers for later completion.

## Fixture policy

The supplied 39-page `IMG_0218 (Merged)(1).pdf` is not committed. It should be used operator-locally after a licensing/privacy review. A future fixture manifest may record its SHA-256, expected 39-page accounting, and approved derived crops without placing the original binary in the public repository.

## Acceptance gates

1. 100% source accounting and source hash coverage.
2. 100% successfully rendered-frame hash coverage; rendering failures explicitly accounted.
3. Device time remains separate from replay time.
4. Stage 2 cannot run before Stage 1 freeze.
5. Correlation cannot run before both freezes.
6. Pixel-space track product exists before registered-track product.
7. Fixed-bounds promotion is false by contract.
8. SATIM schema contains no operational-purpose or intent class.
9. Correlation causal status is always `not_assessed`.
10. Identical source bytes plus mode produce the same run ID.

## Current limitations

This first implementation establishes the skill contract, deterministic package, stage gates, CLI, schemas, and adapters. It does not claim that every legacy OCR, route-vector, affine-calibration, or SATIM command has a uniform import-safe API. Adapter warnings identify those integration points for the next increment. External imagery acquisition is not performed automatically in v0.1.

## Operator command

```bash
python -m fr24_image_skill run "/path/to/input" --output-dir "/path/to/output" --mode forensic
```
