# FR24 Image Analysis Skill — Fixture Validation v0.2

## Target

- Pull request: #98
- Branch: `codex/skywatcher-fr24-image-analysis-skill-v0-1`
- Original PR head tested by GitHub Actions: `e367eff67f3c510a4cde51ba6d80ad427d4eb231`
- Operator-local fixture: `IMG_0218 (Merged)(1).pdf`
- Fixture handling: not committed; local validation only pending licensing/privacy review.

## GitHub Actions status

All pull-request workflows associated with the original PR head completed successfully:

- Skywatcher CI: success on Python 3.10, 3.11, and 3.12
- Imagery test matrix: success on Python 3.11 and 3.12
- SATIM Runtime Smoke Tests: success
- Federation template drift: success

The repository CI test command includes the added `tests/test_fr24_image_skill.py` through the standard test collection. The dedicated command and CLI smoke test remain documented operator commands:

```bash
pytest -q tests/test_fr24_image_skill.py tests/test_fr24_image_skill_adapters.py
python -m fr24_image_skill --help
```

## Local fixture validation

The fixture was rendered with `pdftoppm -png -r 72` in an isolated local workspace. Original and derived files were SHA-256 hashed. No fixture media was written to the repository.

| Gate | Result |
|---|---:|
| PDF page count | 39 / 39 |
| Source accounting | 100% |
| Frame accounting | 39 / 39 |
| Frame SHA-256 coverage | 100% |
| Source SHA-256 | `8e5307c999d53e3ea0185caaa33cbbe2a8e994e271b34ac31712846b15d5aecf` |
| Deterministic local summary rerun | Match |
| Deterministic summary digest | `c28221cb1bea0b0e45d126157ef51260f8e02ea6272c76c3d1b31879d11b4e82` |
| Registration OCR candidate | `N6654G` |
| Green route detected | Pages 1, 3, 4, and 5 |
| Geographic registration | Explicitly unregistered; no fixed-bounds promotion |
| Device/replay time fields | Separate by schema |

## SATIM triage result

A conservative gradient detector produced 36 possible seam candidates across the 39 rendered pages. This is deliberately a high-recall triage count, not 36 certified tile seams. Every candidate requires repeat-view and ground-alignment adjudication. Dark areas remain unresolved among shadow, water, exposed ground, and mosaic/rendering effects.

## Adapter hardening

`fr24_image_skill/adapters.py` replaces command-help probing with an import-safe typed capability registry for:

- UI segmenter
- region OCR
- RLSM OCR
- flight fusion
- track vectorizer
- affine georegistration
- SATIM engine
- tile-seam classifier

Unavailable symbols are represented as explicit degraded capability states. They do not generate synthetic analytical outputs.

## Known limitations

1. The local fixture validation exercised deterministic rendering, hashing, OCR triage, route-color detection, and seam-candidate triage. It did not certify an exact geographic track.
2. A registered track remains prohibited until a validated multi-anchor affine solution exists and its residual/error fields are recorded.
3. SATIM candidates are descriptive observations only. Facility purpose, mission, causation, and flight intent remain outside scope.
4. Apple Maps/FR24 basemap acquisition metadata were not available from the screenshots.
5. The typed registry reports interface availability; repository-native adapters still require per-module integration tests before production promotion.

## Disposition

The implementation remains a draft. Merge is not authorized by this report.
