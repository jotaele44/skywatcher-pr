# Flight Corpus V4 data layer

This directory is the repository landing zone for application-consumable V4 derivatives.

The monolithic source/evidence ZIP is intentionally not committed here.

Every imported dataset MUST:
1. appear in `import_manifest.json`;
2. carry its own SHA-256;
3. preserve its V4 role and lineage state;
4. remain reproducible from the frozen V4 evidence artifact or original RAW source;
5. preserve UNKNOWN/BLOCKED/UNRESOLVED states;
6. never promote geometry/proximity/owner/callsign into mission, coordination, operator, or airframe identity.

Import is fail-closed. Missing expected files, hash mismatches, denominator mismatches, duplicate dataset IDs/paths, or an invalid role/state make validation fail.

The V4 evidence ZIP remains external until its exact artifact hash and selected member hashes are supplied to the importer. No placeholder hash is canonical.
