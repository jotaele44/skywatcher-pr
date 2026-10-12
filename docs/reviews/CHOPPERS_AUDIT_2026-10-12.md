# Choppers.zip — bounded helicopter corpus audit (2026-10-12)

**State: AUDIT_ONLY, NOT CERTIFIED, NOT A PRODUCTION RELEASE.** This is a review artifact; no changes to flight ownership, ingestion, GUI, API, or canonical federation packages are implied.

## Frozen input
- User-supplied Project Sources archive: `Choppers.zip`
- Size: 73,065,927 bytes
- SHA-256: `a4de8fe8ddd9f893a2e89306367a4de8fd21bab280c8de0a491c40774fdf0677`
- Outer ZIP members (including directories and macOS sidecars): **5,664**
- Non-directory, non-`__MACOSX/` payload members: **2,810**
- `SOURCE_MANIFEST.csv`: **956** indexed file paths; **0** hash mismatches or byte-size mismatches on paths present in both sets; **1,887** payload paths unlisted; **34** manifest paths missing from the archive.
- **106** same-size+SHA256 payload-duplicate groups (220 members), preserving distinct paths instead of merging.

## Flight summary — canonical source selection
The archive's `STANDARD_FORMAT_README.txt` declares each top-level `<aircraft>/<aircraft>_combined.csv` one-leg-per-row log to be canonical. Never add `by_day/`, `by_month/`, `source_flight_files/`, `raw_points/` or KML copies to the flight count.

- **740** top-level canonical legs, **26** aircraft strings, point counts summing to **337,002**.
- Top-level canonical flight-key collisions: **0**; row timestamp/coordinate/schema errors: **0**.
- The two indexes also refer to N999ZY, whose top-level summary is absent. Its `N999ZY/raw_points/N999ZY_combined.csv` provides **31,753** tagged telemetry points over **76** LegIDs. Reconstructed legs are **CANDIDATE** source-derived records, not a resurrected authoritative top-level summary.
- Reconciled *bounded dataset*: **816** leg keys, **368,755** point counts and **27** aircraft strings; daily and monthly indexes both agree exactly, with **zero** residual count mismatches.
- Additional source directories `N173B`, `N691CM`, and `PSIVZ` lack canonical combined summaries in this bounded index. Their records require separate intake/adjudication. No claim of total archive flight exhaustiveness.
- Registrations/callsigns are not stable airframe identities.

## Spatial reference and enrichment
Nine Spiderweb airport *point references* from `spiderweb-pr/exports/real/observations.jsonl`, Git blob `5dfb03703331bd76eca68eb175eb97bc88aefc08`, were used to compute endpoint proximity with a **3 km** radius:
- **1,632** start/endpoints tested.
- **1,009** point-proximity associations (multiple candidate matches per endpoint are possible).
- All are `CANDIDATE_NOT_IDENTITY`, `COMPUTED`, `UNREVIEWED`.
- Not runway footprints, confirmed arrivals/departures, flight purpose, or a complete aviation GIS catalog.

The Spiderweb point subset has 9 ICAO-tagged rows; the Skywatcher local airport registry includes 19 entries but only 7 exact ICAO-code intersections with this subset. Two Spiderweb ICAOs are unmatched by code and at least one common code (TJRV) has material coordinate disagreement (~1.7 km). Never merge source records on name, nearest distance, or count equality. Source-classification differences are not identity.

## Certification gates
| Gate | Outcome |
| --- | --- |
| ZIP member hash audit on manifest intersection | PASS (bounded intersection only) |
| Archive manifest coverage | **FAIL** (1,887 unlisted, 34 missing) |
| Canonical root-log row checks | PASS (740 rows only) |
| N999ZY reconstructed raw-point count | PASS (76 legs / 31,753 points), **CANDIDATE** |
| Both archive indexes and unique reconciled keys | PASS (816 / 368,755) |
| Geographic point proximity arithmetic | AUDIT_ONLY |
| Full raw-track vs KML trajectory parity | OPEN |
| Geometric/temporal identity certification | OPEN |
| GUI/API parity and rendered client verification | OPEN |
| Live Skywatcher canonical export → TheHub validation | BLOCKED |
| Production merge/release | **BLOCKED** |

## Implementation boundary
Skywatcher owns flight ingestion and FPIM. Spiderweb provides source-specific geographic reference products. TheHub owns cross-producer federation admission/correlation. Respect `spiderweb-pr/docs/ADR_SKYWATCHER_SPIDERWEB_INTEGRATION.md`, which forbids bespoke direct repo-to-repo connectors.

Local reproducible evidence bundle includes `choppers_audit.py`, `choppers_reconcile_enrich.py`, `test_choppers_release.py`, 2 JSON gate reports, full member hash list, flight rows, spatial candidate links, and SHA-256 outputs. Keep this review branch unmerged until raw archive/geometry/consumer/GUI gates are closed with frozen evidence.

## Follow-up vector
1. Adjudicate the 1,887/34 manifest scope differences, including time/path exclusions, without retroactive rewriting.
2. Validate raw telemetry to summary and KML geometries for all retained leg IDs.
3. Resolve `N173B/N691CM/PSIVZ` and airport-code/geometry differences independently.
4. Publish a canonical non-synthetic Skywatcher package; validate admission in TheHub on an actual immutable input snapshot.
5. Run producer/consumer/API/GUI regression suites and preserve commit SHA, CI run URLs, hashes, reviewed outputs and release decision. Train the reusable skill/agent **after** passing its golden-case and negative-case gates.

## Addendum: independent raw-point parity gate (2026-10-12)

A subsequent exhaustive scan of the **26 consolidated raw-point CSV members** read **356,201 raw records** and compared them by (Callsign, LegID) with all 816 reconciled flight keys:
- **804** flight keys match the advertised point count exactly (356,199 matched raw rows).
- **11** N167C flight legs, totaling **12,554** advertised points, have no consolidated raw-point CSV in this selected archive lane.
- **1** N409TD flight leg, `409f1b26` (2 points), has two raw records containing a **blank callsign** and the matching LegID. Those remain **unassigned candidate telemetry**, not silently rewritten.
- **0** mismatched counts among matched flight keys, **2** unmatched raw rows and **12** total legs without exact compound-key raw parity.
- **Raw parity certification gate: FAIL.** The index closure remains PASS and must not be confused with raw telemetry parity. The standalone audit bundle includes `raw_parity.json`, `raw_parity_legs.csv` and a negative regression for this exact condition.

This addendum does not authorize inference of aircraft identity from LegID alone. The affected two raw records require explicit source adjudication.
