# Floot reconciliation: persistence safety adjudication

State: PROVISIONAL implementation; portable execution AUDIT_ONLY; iOS acceptance OPEN.

## Frozen scope

Repository: jotaele44/skywatcher-pr; draft PR #273.
Base head: 1230bd0bbb906a408eb1bab2f0efe9c1647f4165.
Original MobilePersistenceStore.swift: Git blob c4f04c440c44872ecae047a5ee83ac03ef5ce1ac; SHA256 29d43de0a0e9c660f21324dbd3f6a08ce3473234b6944eaadb1baaee2d67122c.
Patched source: Git blob 1680741b1c280144f26ebb3348958b34a1c0ad90; SHA256 5965e9a4d77dc6491c4f11a8c2e3aedd52b7e0a326b58133008145bfbf3aa706.
New safety tests: Git blob 0cf91a25c13d2580c676f2c92ae9557caf1a6041; SHA256 381c6ad286edbb97c23fdf9689233c8abf1094a1f21175e7f880f4ceba1d4c77.

## Reproduced defects and supersession

The original source passed a normal backup/restore probe, but after a process exited without closing/checkpointing, a hash-valid corrupt restore discarded an admitted value that existed only in WAL. The original implementation also admitted a tampered migration digest and truncated an embedded-NUL workspace key, overwriting another raw key. The earlier blanket claim that failed restore preserves the admitted database is SUPERSEDED.

The candidate preserves the committed WAL value in that probe, rejects the tampered ledger, and rejects NUL text without normalizing it into another key. Observations are retained in fault-probes.json. These probes exercise the actual original/candidate Swift class against Linux SQLite with a substitute SHA256 dependency; they are not iOS executions.

## Implemented safeguards

Restore validates a private, hash-bound standalone candidate before accessing the target. Existing destinations use SQLite's backup transaction; the code never unlinks a live database or its WAL/SHM. New backups refuse existing destinations. Same-file/hard-link restore aliases are rejected. A governed-schema/ledger check rejects unexpected tables and inconsistent migration records. Source and destination schema checks are rejection gates, not proof of producer identity or source provenance. App-specific authority binding and lifecycle coordination remain required.

Migrations verify recorded versions, names and SQL digests and run transactionally. Integer arithmetic is overflow-checked. Embedded-NUL text is rejected, empty data binds as an empty BLOB rather than NULL, and instance operations are serialized. The migration SQL bytes and producer/domain authority tables are not changed.

## Executed evidence

Swift 6.2.1, x86_64-unknown-linux-gnu, warnings treated as errors. CryptoKitAuditShim.swift uses OpenSSL SHA256 instead of Apple's CryptoKit. The shim lives outside iOS sources and is not an application dependency.

20 distinct safety XCTest methods executed; 20 passed; 0 failed. Frozen log: portable-xctest.log; SHA256 cad9ca91c613e21fd13e7e5915422ecee1e84ad0244fc81e4ea4220759901d13. The checked-in reproduction script was also executed successfully with the same frozen source and test hashes. A second run is not 20 additional distinct tests. The seven older LocalPersistenceTests were inspected but are not included in this 20-test execution denominator.

Reproduce on Linux with Swift, Python 3, SQLite development headers and OpenSSL development headers:

    bash reports/floot-reconciliation/2026-09-13/run_portable_audit.sh /tmp/new-audit-log.txt

The script refuses a changed source/test digest, a different test denominator, missing execution evidence, or an existing output log. It does not certify or merge anything.

## Archive count correction

The preserved eight-archive bundle SHA256 is 7c68d691e4f826200afb1d1650aa780da4e8a7910dea924b7c08924c48e338fe. Re-reading original ZIP entries and hashing all payloads yields 2407 entries = 106 directories + 2301 files. The prior 2202 aggregate is SUPERSEDED; each individual prior manifest count was correct. Archive manifests versus source ZIP payloads: INTERSECTION 2301; MANIFEST_ONLY 0; ARCHIVE_ONLY 0; UNION 2301; SYMMETRIC_DIFFERENCE 0. This is local archive/manifest equivalence, not remote source-import completion. No original archive or manifest bundle is rewritten.

## Gates still open

No claim of Apple compilation, full application or share-extension execution, iOS cold launch, force-termination/relaunch, device migration/rollback, device backup/restore, physical power-loss behavior, concurrent app/extension coordination, network-denied runtime, or Floot-unreachable acceptance. The native run at the prior exact head failed without reported steps; startup cause remains unresolved. The native workflow and project settings remain unchanged. All merge/release/Floot-retirement authorization gates remain closed.

Five other repository manifest uploads, MoneySweep's full 19-object independent SHA256 rehash, OVNIS's four missing historical byte manifestations, and Floot DB/asset/browser-workspace recovery are not closed by this safety patch. No public-source exhaustion is asserted.
