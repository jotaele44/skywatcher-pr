# Legacy infrastructure provenance migration v0.3

This migration moves the complete 24-row hardcoded infrastructure denominator
into a schema-locked source manifest. The exact Git head, file path, and blob SHA
prove the **code manifestation** from which each assertion originated.

That provenance does not prove real-world identity or geometry. Every row stays:

- `AUDIT_ONLY`
- `CANDIDATE_NOT_IDENTITY`
- `coordinate_method = UNKNOWN`
- `production_admitted = false`

Coordinate collisions are preserved as contradictions, not deduplicated. The
legacy `SIG` row remains preserved raw but its `HELIPORT` classification is
`SUPERSEDED`; the FAA-backed TJIG airport identity is the harder observation.

Runtime cutover remains blocked until each row has an authoritative source
manifestation or an exact Spiderweb geometry binding. Downstream proximity
results from these rows remain discovery signals only.
