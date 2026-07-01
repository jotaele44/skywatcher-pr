# SATIM v19 hardening notes

- Parser now distinguishes `NonTrackCSV` from true parser errors.
- CSV ingestion uses UTF-8/UTF-8-SIG/Latin-1/CP1252 fallback.
- Added visual OCR plugin interface with safe filename fallback.
- Added GIS join plugin interface with bbox-context fallback.
- Added skipped non-track CSV ledger for auditability.
