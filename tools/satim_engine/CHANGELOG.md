# Changelog

## 0.21.0-rc1 — SATIM_BATCH_v21

### Added
- GitHub Actions CI workflow for tests and CLI smoke test.
- Release candidate version tag.
- Release candidate package metadata.

### Changed
- Cleaned non-blocking pandas concat warning by filtering empty/all-NA track frames before concatenation.
- Promoted v19 production engine and v20 operational run outputs into a release-candidate structure.

### Validation
- Unit tests pass.
- Full source batch remains operational.
- Parser errors remain at zero.
