# Executable binding checkpoint — laboratory only

Operation: sky-core-v0.1.0/06
Parent: a4e3cb6ad0d94d7b7b07b51cc690a9bda40a8989

Adds an opt-in binding layer over LensRegistry. Trusted composition code supplies
callables; configuration cannot specify imports or commands. Empty discovery
and resolution are supported; no objective is certified by empty selection.
The semantic digest is not a source-byte hash or executable integrity receipt.
No default adapters, production dispatch, API, or GUI wiring are introduced.
The test adapter is synthetic. Real SATIM/FPIM adapters, schema validation,
calibration receipts, source identity, TheHub authorization and durable execution
remain unimplemented. Do not promote this laboratory surface.

Prior candidate CI: 7/9 observed workflows successful; Skywatcher CI frontend
Install and lock validation failed; GUI Reachability E2E npm ci failed.
Backend Python matrix, imagery, ADS-B and lint jobs succeeded.
New exact-head checks required. FLIPA identity unresolved.
