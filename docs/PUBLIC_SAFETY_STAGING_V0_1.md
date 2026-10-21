# PITIRRE public-safety staging v0.1

Status: AUDIT_ONLY. No production integration or live ingestion.

Scope: historical official-source event metadata and non-identifying public aggregates for missing persons, trafficking, maritime rescue, migrant smuggling, and interdictions. These are separate event categories; no causal or identity inference from co-location.

Existing AIR, LAND, WATER, SPACE domain contracts remain unchanged. Spiderweb retains geometry authority; PRIIS adjudicates relationships; TheHub is the eventual visualization consumer.

Gates: preserve baseline; validate contract; independently run unit and adversarial tests; acquire and freeze authorized sources; reconcile unique source record identifiers; exercise integrated acceptance and rollback; confirm exact-head CI and security; release only on PASS. All live and integrated gates remain OPEN or BLOCKED.

Local check: `PYTHONPATH=src python3 -m unittest discover -s tests -p test_public_safety_records.py -v`

Fail closed if evidence, test environment, identity resolution, or authorization is missing. No names, private details, precise live locations or individual criminal suspicion predictions in public outputs.
