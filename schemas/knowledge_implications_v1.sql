-- Skywatcher implication sidecar V0.1 (DRAFT / opt-in). No replacement of MFL,
-- schemas/database_schema.sql, schemas/flight_corpus.sql, or RLSM database.
-- Compatible with SQLite; install only after repository migration tests pass.
-- All cross-database references use namespace + frozen source snapshot keys.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS swk_source_artifact (
  artifact_id TEXT PRIMARY KEY,
  source_namespace TEXT NOT NULL CHECK(source_namespace IN
    ('SKYWATCHER_PRIMARY','RLSM_LOCAL','MFL_SNAPSHOT','EXTERNAL','USER_UPLOAD')),
  external_source_key_raw TEXT NOT NULL,
  source_snapshot_sha256 TEXT CHECK(source_snapshot_sha256 IS NULL OR
    (length(source_snapshot_sha256)=64 AND source_snapshot_sha256 NOT GLOB '*[^0-9a-f]*')),
  byte_sha256 TEXT CHECK(byte_sha256 IS NULL OR
    (length(byte_sha256)=64 AND byte_sha256 NOT GLOB '*[^0-9a-f]*')),
  source_kind TEXT NOT NULL,
  source_uri_raw TEXT,
  retrieval_utc TEXT,
  source_epoch_raw TEXT,
  evidence_tier TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(evidence_tier IN ('T1','T2','T3','T4','UNKNOWN')),
  visibility_class TEXT NOT NULL DEFAULT 'V2' CHECK(visibility_class IN ('V0','V1','V2','V3','V4')),
  provenance_status TEXT NOT NULL DEFAULT 'INCOMPLETE' CHECK(provenance_status IN ('COMPLETE','INCOMPLETE','UNKNOWN')),
  availability TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(availability IN ('PRESENT','MISSING','RESTORED','ARCHIVED','UNKNOWN')),
  created_utc TEXT NOT NULL
);
-- Byte identity is never interpreted as logical event identity. Preserve every
-- observed path / export in this child table even for identical artifact bytes.
CREATE TABLE IF NOT EXISTS swk_artifact_manifestation (
  manifestation_id TEXT PRIMARY KEY,
  artifact_id TEXT NOT NULL REFERENCES swk_source_artifact(artifact_id),
  source_path_raw TEXT,
  source_record_key_raw TEXT,
  observed_utc TEXT NOT NULL,
  manifestation_metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(manifestation_metadata_json))
);
CREATE INDEX IF NOT EXISTS ix_swk_artifact_manifestations_artifact
  ON swk_artifact_manifestation(artifact_id);

-- External keys are scoped to their namespace and frozen source manifestation;
-- they do not automatically bind to a canonical flight.
CREATE TABLE IF NOT EXISTS swk_subject_ref (
  subject_id TEXT PRIMARY KEY,
  subject_kind TEXT NOT NULL CHECK(subject_kind IN
    ('MFL_RECORD','RLSM_SCREENSHOT','RECONSTRUCTED_FLIGHT','AIRCRAFT_CANDIDATE',
     'AOI','FPIM_FINDING','SATIM_FINDING','CORRIM_ASSOCIATION','OTHER')),
  source_namespace TEXT NOT NULL,
  external_record_key_raw TEXT NOT NULL,
  source_snapshot_sha256 TEXT,
  identity_state TEXT NOT NULL DEFAULT 'UNRESOLVED' CHECK(identity_state IN
    ('PASS','PROVISIONAL','OPEN','CANDIDATE_NOT_IDENTITY','UNRESOLVED','SUPERSEDED')),
  binding_basis_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(binding_basis_json)),
  created_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_swk_subject_external
  ON swk_subject_ref(source_namespace, external_record_key_raw, source_snapshot_sha256);

-- Candidate identity and its full evidence set; this is NOT a new flight log.
CREATE TABLE IF NOT EXISTS swk_subject_evidence (
  subject_id TEXT NOT NULL REFERENCES swk_subject_ref(subject_id),
  artifact_id TEXT NOT NULL REFERENCES swk_source_artifact(artifact_id),
  relation TEXT NOT NULL CHECK(relation IN ('SUPPORT','COUNTEREVIDENCE','CONTROL','CONTEXT','EXCLUDED')),
  binding_state TEXT NOT NULL CHECK(binding_state IN
    ('PASS','OPEN','PROVISIONAL','UNRESOLVED','REJECTED','SUPERSEDED')),
  evidence_basis_json TEXT NOT NULL CHECK(json_valid(evidence_basis_json)),
  PRIMARY KEY(subject_id,artifact_id,relation)
);

CREATE TABLE IF NOT EXISTS swk_knowledge_run (
  run_id TEXT PRIMARY KEY,
  input_manifest_sha256 TEXT NOT NULL CHECK(length(input_manifest_sha256)=64),
  ruleset_sha256 TEXT NOT NULL CHECK(length(ruleset_sha256)=64),
  baseline_commit TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','VALIDATED','FAILED','BLOCKED')),
  started_utc TEXT NOT NULL,
  finished_utc TEXT,
  diagnostics_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(diagnostics_json))
);

CREATE TABLE IF NOT EXISTS swk_implication (
  implication_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES swk_knowledge_run(run_id),
  domain_owner TEXT NOT NULL CHECK(domain_owner IN ('SATIM','FPIM','CORRIM')),
  implication_type TEXT NOT NULL CHECK(implication_type IN
    ('LOCAL','CORPUS','CONTROL','MODEL','COVERAGE','CONTRADICTION')),
  epistemic_class TEXT NOT NULL CHECK(epistemic_class IN ('INFERENCE','COMPUTED','UNKNOWN')),
  delta_type TEXT NOT NULL CHECK(delta_type IN
    ('NEW','CONFIRMS','STRENGTHENS','WEAKENS','CONTRADICTS','REFINES',
     'NARROWS','BROADENS','EXTENDS_TEMPORAL_RANGE','EXTENDS_SPATIAL_RANGE',
     'IMPROVES_SOURCE_QUALITY','CLOSES_GAP','CREATES_GAP','REOPENS','CLOSES',
     'SUPERSEDES','NO_MATERIAL_CHANGE')),
  statement TEXT NOT NULL CHECK(length(trim(statement))>0),
  scope_json TEXT NOT NULL CHECK(json_valid(scope_json)),
  ruleset_version TEXT NOT NULL,
  dependency_sha256 TEXT NOT NULL CHECK(length(dependency_sha256)=64),
  validity_state TEXT NOT NULL DEFAULT 'CURRENT' CHECK(validity_state IN
    ('CURRENT','STALE','INVALIDATED','SUPERSEDED','RECOMPUTED')),
  certification_state TEXT NOT NULL DEFAULT 'OPEN' CHECK(certification_state IN
    ('PASS','FAIL','OPEN','BLOCKED','PROVISIONAL','AUDIT_ONLY','UNRESOLVED','SUPERSEDED')),
  prior_state_id TEXT,
  new_state_id TEXT,
  supersedes_id TEXT REFERENCES swk_implication(implication_id),
  created_utc TEXT NOT NULL,
  CHECK (certification_state <> 'PASS' OR validity_state IN ('CURRENT','RECOMPUTED'))
);
CREATE INDEX IF NOT EXISTS ix_swk_imp_run ON swk_implication(run_id);

-- Supports multiple independent sources and expressly labeled control evidence.
CREATE TABLE IF NOT EXISTS swk_implication_evidence (
  implication_id TEXT NOT NULL REFERENCES swk_implication(implication_id),
  artifact_id TEXT NOT NULL REFERENCES swk_source_artifact(artifact_id),
  evidence_role TEXT NOT NULL CHECK(evidence_role IN
    ('SUPPORT','COUNTEREVIDENCE','CONTROL','CONTEXT','FALSIFIER','REQUIRED')),
  PRIMARY KEY(implication_id,artifact_id,evidence_role)
);
CREATE TABLE IF NOT EXISTS swk_implication_subject (
  implication_id TEXT NOT NULL REFERENCES swk_implication(implication_id),
  subject_id TEXT NOT NULL REFERENCES swk_subject_ref(subject_id),
  subject_role TEXT NOT NULL CHECK(subject_role IN
    ('ABOUT','SUPPORT','COUNTEREVIDENCE','CONTROL','CONTEXT')),
  PRIMARY KEY(implication_id,subject_id,subject_role)
);
-- No self-support; transitive cycles and stale dependencies are verified by
-- the application validator, not hidden in SQL joins.
CREATE TABLE IF NOT EXISTS swk_implication_lineage (
  implication_id TEXT NOT NULL REFERENCES swk_implication(implication_id),
  parent_implication_id TEXT NOT NULL REFERENCES swk_implication(implication_id),
  relation TEXT NOT NULL CHECK(relation IN ('DERIVED_FROM','WEAKENS','SUPERSEDES','CONTRADICTS')),
  PRIMARY KEY(implication_id,parent_implication_id,relation),
  CHECK(implication_id <> parent_implication_id)
);

-- A run receipt describes the externally certified MFL denominator. Never
-- compute a canonical event count from screenshot/source/join rows here.
CREATE TABLE IF NOT EXISTS swk_knowledge_state (
  state_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES swk_knowledge_run(run_id),
  previous_state_id TEXT REFERENCES swk_knowledge_state(state_id),
  source_manifestation_count INTEGER NOT NULL CHECK(source_manifestation_count>=0),
  canonical_event_count INTEGER CHECK(canonical_event_count IS NULL OR canonical_event_count>=0),
  canonical_denominator_ref TEXT,
  canonical_denominator_sha256 TEXT,
  canonical_denominator_cert_receipt TEXT,
  unresolved_candidate_count INTEGER NOT NULL CHECK(unresolved_candidate_count>=0),
  implication_count INTEGER NOT NULL CHECK(implication_count>=0),
  contradiction_count INTEGER NOT NULL CHECK(contradiction_count>=0),
  state_manifest_sha256 TEXT NOT NULL CHECK(length(state_manifest_sha256)=64),
  certification_state TEXT NOT NULL CHECK(certification_state IN
    ('PASS','OPEN','BLOCKED','PROVISIONAL','AUDIT_ONLY','UNRESOLVED')),
  created_utc TEXT NOT NULL,
  CHECK(canonical_event_count IS NULL OR
    (canonical_denominator_ref IS NOT NULL AND canonical_denominator_sha256 IS NOT NULL)),
  CHECK(certification_state <> 'PASS' OR
    (canonical_denominator_ref IS NOT NULL AND canonical_denominator_sha256 IS NOT NULL
     AND canonical_denominator_cert_receipt IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS swk_knowledge_delta (
  delta_id TEXT PRIMARY KEY,
  prior_state_id TEXT NOT NULL REFERENCES swk_knowledge_state(state_id),
  new_state_id TEXT NOT NULL REFERENCES swk_knowledge_state(state_id),
  dimension TEXT NOT NULL,
  delta_type TEXT NOT NULL,
  before_json TEXT NOT NULL CHECK(json_valid(before_json)),
  after_json TEXT NOT NULL CHECK(json_valid(after_json)),
  explanation_json TEXT NOT NULL CHECK(json_valid(explanation_json)),
  CHECK(prior_state_id <> new_state_id)
);
CREATE TABLE IF NOT EXISTS swk_contradiction (
  contradiction_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES swk_knowledge_run(run_id),
  contradiction_class TEXT NOT NULL CHECK(contradiction_class IN
    ('BYTE','SCHEMA','GEOMETRY','NAME','COUNT','CLASS','IDENTITY','TIME','SCOPE')),
  observation_a_ref TEXT NOT NULL,
  observation_b_ref TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('OPEN','PARTIAL','RESOLVED','UNRESOLVED','SUPERSEDED')),
  resolution_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(resolution_json)),
  created_utc TEXT NOT NULL
);

-- PASS cannot be set without a bound supporting artifact. This covers both
-- insert and update. A later invalidation must change certification in one UPDATE.
CREATE TRIGGER IF NOT EXISTS tr_swk_imp_pass_insert
BEFORE INSERT ON swk_implication
WHEN NEW.certification_state='PASS'
BEGIN SELECT RAISE(ABORT, 'PASS requires evidence inserted first'); END;
CREATE TRIGGER IF NOT EXISTS tr_swk_imp_pass_update
BEFORE UPDATE OF certification_state ON swk_implication
WHEN NEW.certification_state='PASS' AND NOT EXISTS (
  SELECT 1 FROM swk_implication_evidence d
  JOIN swk_source_artifact s ON s.artifact_id=d.artifact_id
  WHERE d.implication_id=NEW.implication_id AND d.evidence_role='SUPPORT'
)
BEGIN SELECT RAISE(ABORT, 'PASS requires a bound supporting source'); END;

-- A PASS implication cannot lose its final direct supporting source silently.
CREATE TRIGGER IF NOT EXISTS tr_swk_support_delete
BEFORE DELETE ON swk_implication_evidence
WHEN OLD.evidence_role='SUPPORT'
 AND (SELECT certification_state FROM swk_implication
      WHERE implication_id=OLD.implication_id)='PASS'
 AND (SELECT COUNT(*) FROM swk_implication_evidence
      WHERE implication_id=OLD.implication_id AND evidence_role='SUPPORT')<=1
BEGIN SELECT RAISE(ABORT,'PASS requires support; reopen or invalidate first'); END;

-- Changing the immutable identity or provenance of a source requires a new row.
-- Availability changes are deliberately versioned elsewhere, not rewritten here.
CREATE TRIGGER IF NOT EXISTS tr_swk_source_immutable
BEFORE UPDATE OF source_namespace,external_source_key_raw,source_snapshot_sha256,
                 byte_sha256,source_kind,source_uri_raw,retrieval_utc,source_epoch_raw
ON swk_source_artifact
BEGIN SELECT RAISE(ABORT,'source identity/provenance is immutable'); END;

CREATE TRIGGER IF NOT EXISTS tr_swk_support_update
BEFORE UPDATE OF evidence_role,artifact_id,implication_id ON swk_implication_evidence
WHEN OLD.evidence_role='SUPPORT'
 AND (SELECT certification_state FROM swk_implication
      WHERE implication_id=OLD.implication_id)='PASS'
 AND (SELECT COUNT(*) FROM swk_implication_evidence
      WHERE implication_id=OLD.implication_id AND evidence_role='SUPPORT')<=1
BEGIN SELECT RAISE(ABORT,'PASS support is immutable; reopen first'); END;

-- The statement and analytical basis of a certified implication are versioned
-- by adding another object, never edited in place.
CREATE TRIGGER IF NOT EXISTS tr_swk_pass_content_immutable
BEFORE UPDATE OF domain_owner,implication_type,epistemic_class,delta_type,
                 statement,scope_json,ruleset_version,dependency_sha256,run_id
ON swk_implication
WHEN OLD.certification_state='PASS'
BEGIN SELECT RAISE(ABORT,'certified implication is immutable; supersede it'); END;
