"""Structural invariants for the Skywatcher analytical ontology governance set.

This suite used to *be* the v2.0 freeze: it pinned exact row counts, asserted the
authorization booleans were all False, and SHA-256'd every governance artifact so
none of them could change. ADR v2.1 decision A0 lifted that lock so the registries
could become living documents (see
docs/architecture/ADR_SKYWATCHER_ANALYTICAL_ONTOLOGY_v2_1.md).

Unfreezing the ontology is not the same as leaving it unchecked. What the freeze
protected — well-formed registries, complete threshold records, recognized statuses,
no silent reinterpretation of history — is still enforced here, as invariants that
hold at any size rather than as a fixed snapshot:

  * every governance CSV parses, has the expected header, and has unique non-blank
    keys;
  * every threshold row carries a complete ADR-section-12 record;
  * every migration row carries a recognized approval state;
  * the frozen v2.0 baseline archived under docs/architecture/archive/v2_0/ still
    recomputes to the hashes recorded at freeze time, so the pre-unfreeze state
    stays provable and a re-freeze stays possible.

Row counts are deliberately NOT asserted. Adding a term or a threshold is now normal
work; regressing the shape of the registry is not.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCH = REPO_ROOT / "docs" / "architecture"
ARCHIVE = ARCH / "archive" / "v2_0"
MANIFEST_PATH = ARCH / "SKYWATCHER_ONTOLOGY_FREEZE_MANIFEST_v2_0.json"

CSV_HEADERS = {
    "SKYWATCHER_TERM_OWNERSHIP_MATRIX_v2_0.csv": [
        "term_id", "canonical_term", "category", "owner", "status",
        "definition", "prohibited_uses",
    ],
    "SKYWATCHER_LEGACY_ALIAS_REGISTRY_v2_0.csv": [
        "legacy_term", "canonical_replacement", "status", "confirmed_paths",
    ],
    # effective_version and supersedes were added by ADR v2.1 A2: a threshold may
    # only execute once it carries a complete section-12 record, and lineage is
    # part of that record.
    "SKYWATCHER_THRESHOLD_REGISTRY_SEED_v2_0.csv": [
        "threshold_id", "owner", "current_value", "unit", "purpose", "status",
        "validation_artifact", "failure_behavior", "effective_version", "supersedes",
    ],
    "SKYWATCHER_PATH_LEVEL_MIGRATION_PLAN_v2_0.csv": [
        "phase", "path", "target_owner", "planned_action", "change_type",
        "compatibility_strategy", "required_tests", "approval_state",
        "open_pr_overlap", "blocking_treatment",
    ],
    "SKYWATCHER_ONTOLOGY_SOURCE_REGISTER_v2_0.csv": [
        "path", "source_family", "use",
    ],
}

UNIQUE_KEYS = {
    "SKYWATCHER_TERM_OWNERSHIP_MATRIX_v2_0.csv": ("term_id", "canonical_term"),
    "SKYWATCHER_LEGACY_ALIAS_REGISTRY_v2_0.csv": ("legacy_term",),
    "SKYWATCHER_THRESHOLD_REGISTRY_SEED_v2_0.csv": ("threshold_id",),
    "SKYWATCHER_PATH_LEVEL_MIGRATION_PLAN_v2_0.csv": ("path",),
    "SKYWATCHER_ONTOLOGY_SOURCE_REGISTER_v2_0.csv": ("path",),
}

ALIAS_STATUSES = {
    "DEPRECATED_COLLISION", "HISTORICAL_ALIAS", "PROHIBITED_INFERENCE_ALIAS",
    "DEPRECATED_METRIC_NAME", "DEPRECATED_INTENT_TERM",
    "PROHIBITED_ACTIVE_ANALYTICS", "UI_SEARCH_ALIAS_ONLY",
    "DEPRECATED_METAPHOR", "PROHIBITED_BARE_TERM", "DEPRECATED_AMBIGUOUS",
    "DEPRECATED_OVERCLAIM", "DEPRECATED_BARE_STATUS", "DEPRECATED_PURPOSE_TERM",
    "MOVE_TO_CORRIM", "PROHIBITED_UNQUALIFIED", "LEGACY_SCHEMA_ALIAS",
    "DEPRECATED_VARIANT",
}

# EXECUTABLE_CANDIDATE and VALIDATED are new in v2.1 A2. PROHIBITED still means
# "must never execute" and is checked separately below.
THRESHOLD_STATUSES = {
    "CANDIDATE", "CANDIDATE_PROJECT_GATE", "PROHIBITED",
    "EXECUTABLE_CANDIDATE", "VALIDATED", "CANONICAL", "CALIBRATION_REQUIRED",
}
EXECUTABLE_THRESHOLD_STATUSES = {"EXECUTABLE_CANDIDATE", "VALIDATED", "CANONICAL"}

APPROVAL_STATES = {
    "AUTHORIZED_G0_ONLY",
    "AUTHORIZED",
    "AUTHORIZED_THRESHOLD_BINDING",
    "BLOCKED_AFTER_G0",
    "BLOCKED_SEPARATE_APPROVAL_REQUIRED",
}


def _read_csv(name: str) -> list[dict[str, str]]:
    path = ARCH / name
    text = path.read_text(encoding="utf-8")
    # chr(0xFFFD), not a literal U+FFFD: embedding the replacement character in this
    # file is the exact corruption the assertion exists to catch.
    assert chr(0xFFFD) not in text, f"replacement character in {name}"
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == CSV_HEADERS[name], (
            f"{name} header drift: {reader.fieldnames}"
        )
        rows = list(reader)
    assert rows, f"empty governance CSV: {name}"
    for key in UNIQUE_KEYS[name]:
        values = [row[key] for row in rows]
        assert all(values), f"blank {key} in {name}"
        assert len(values) == len(set(values)), f"duplicate {key} in {name}"
    return rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_governance_csv_contracts() -> None:
    for name in CSV_HEADERS:
        _read_csv(name)


def test_terms_and_alias_dispositions_are_well_formed() -> None:
    terms = _read_csv("SKYWATCHER_TERM_OWNERSHIP_MATRIX_v2_0.csv")
    assert all(
        row["owner"] and row["definition"] and row["prohibited_uses"] for row in terms
    ), "every canonical term needs an owner, a definition, and prohibited uses"

    aliases = _read_csv("SKYWATCHER_LEGACY_ALIAS_REGISTRY_v2_0.csv")
    assert {row["status"] for row in aliases} <= ALIAS_STATUSES
    assert all(row["canonical_replacement"] and row["confirmed_paths"] for row in aliases)


def test_dual_use_label_is_registered_and_scoped() -> None:
    """ADR v2.1 A1 authorizes a bounded facility-function claim, nothing wider."""
    terms = {row["canonical_term"]: row for row in
             _read_csv("SKYWATCHER_TERM_OWNERSHIP_MATRIX_v2_0.csv")}

    dual_use = terms.get("DUAL_USE_FUNCTION_CANDIDATE")
    assert dual_use is not None, "DUAL_USE_FUNCTION_CANDIDATE must be a registered term"
    assert dual_use["owner"] == "SATIM"
    prohibited = dual_use["prohibited_uses"].lower()
    for forbidden in ("ownership", "intent", "mission", "wrongdoing"):
        assert forbidden in prohibited, (
            f"dual-use term must still prohibit {forbidden!r} claims"
        )


def test_every_threshold_carries_a_complete_section_12_record() -> None:
    rows = _read_csv("SKYWATCHER_THRESHOLD_REGISTRY_SEED_v2_0.csv")
    assert {row["status"] for row in rows} <= THRESHOLD_STATUSES

    for row in rows:
        tid = row["threshold_id"]
        assert row["owner"], f"{tid} has no owner"
        assert row["current_value"], f"{tid} has no value"
        assert row["unit"], f"{tid} has no unit"
        assert row["purpose"], f"{tid} has no purpose"
        assert row["validation_artifact"], f"{tid} has no validation artifact"
        assert row["failure_behavior"], f"{tid} has no failure behavior"
        assert row["effective_version"], f"{tid} has no effective version"


def test_prohibited_thresholds_are_never_executable() -> None:
    """Unfreezing let thresholds execute; it did not un-prohibit the banned ones."""
    rows = _read_csv("SKYWATCHER_THRESHOLD_REGISTRY_SEED_v2_0.csv")
    prohibited = [row for row in rows if row["status"] == "PROHIBITED"]
    assert prohibited, "the prohibited-threshold class must not disappear silently"
    for row in prohibited:
        assert row["status"] not in EXECUTABLE_THRESHOLD_STATUSES


def test_migration_plan_states_are_recognized() -> None:
    rows = _read_csv("SKYWATCHER_PATH_LEVEL_MIGRATION_PLAN_v2_0.csv")
    states = {row["approval_state"] for row in rows}
    assert states <= APPROVAL_STATES, f"unrecognized approval state(s): {states - APPROVAL_STATES}"
    assert all(row["planned_action"] and row["target_owner"] for row in rows)


def test_manifest_records_the_unfreeze() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "skywatcher.ontology_freeze_manifest.v2.1"
    assert manifest["repository"] == "jotaele44/skywatcher-pr"
    assert manifest["status"] == "UNFROZEN_IMPLEMENTATION_AUTHORIZED"

    for field in (
        "schema_change_authorized",
        "runtime_change_authorized",
        "threshold_execution_authorized",
        "workflow_change_authorized",
    ):
        assert manifest[field] is True, f"{field} should be lifted by the unfreeze"

    # A1 authorized a bounded facility-function claim and nothing beyond it. Mission
    # and intent inference stay prohibited; aircraft-type-to-mission deduction stays
    # quarantined in skywatcher.legacy.
    assert manifest["mission_or_intent_inference_authorized"] is False

    assert manifest["unfreeze_date"]
    assert manifest["unfreeze_authority"]
    assert manifest["unfreeze_base_commit"]
    assert manifest["superseding_authority"].endswith("_v2_1.md")
    assert (REPO_ROOT / manifest["superseding_authority"]).is_file()

    # The freeze that happened is still recorded, not rewritten.
    assert manifest["freeze_date"] == "2026-08-03"
    assert manifest["base_commit"] == "140b954b6faa9a50e26ad38fd56b0bc038ea6c25"


def test_frozen_baseline_is_archived_and_still_verifies() -> None:
    """The pre-unfreeze bytes must stay provable, or a re-freeze is impossible."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    records = manifest["frozen_baseline_records"]
    assert records, "the frozen baseline record set must not be empty"

    for record in records:
        path = REPO_ROOT / record["path"]
        assert path.is_file(), f"archived baseline missing: {record['path']}"
        assert path.is_relative_to(ARCHIVE), (
            f"baseline record must point into the archive: {record['path']}"
        )
        assert record["size_bytes"] == path.stat().st_size, record["path"]
        assert record["sha256"] == _sha256(path), record["path"]

    # Everything the v2.0 freeze covered is present in the archive.
    archived = {Path(record["path"]).name for record in records}
    expected = {Path(p).name for p in manifest["authorized_paths"]
                if not p.endswith("SKYWATCHER_ONTOLOGY_FREEZE_MANIFEST_v2_0.json")}
    assert archived == expected, f"archive/manifest mismatch: {archived ^ expected}"
