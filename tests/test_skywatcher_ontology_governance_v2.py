from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCH = REPO_ROOT / "docs" / "architecture"

BASE_SHA = "140b954b6faa9a50e26ad38fd56b0bc038ea6c25"
AUTHORIZED_PATHS = {
    "docs/architecture/ADR_SKYWATCHER_ANALYTICAL_ONTOLOGY_v2_0.md",
    "docs/architecture/SKYWATCHER_TERM_OWNERSHIP_MATRIX_v2_0.csv",
    "docs/architecture/SKYWATCHER_LEGACY_ALIAS_REGISTRY_v2_0.csv",
    "docs/architecture/SKYWATCHER_THRESHOLD_REGISTRY_SEED_v2_0.csv",
    "docs/architecture/SKYWATCHER_PATH_LEVEL_MIGRATION_PLAN_v2_0.csv",
    "docs/architecture/SKYWATCHER_ONTOLOGY_SOURCE_REGISTER_v2_0.csv",
    "docs/architecture/SKYWATCHER_ONTOLOGY_FREEZE_MANIFEST_v2_0.json",
    "tests/test_skywatcher_ontology_governance_v2.py",
}

CSV_HEADERS = {
    "SKYWATCHER_TERM_OWNERSHIP_MATRIX_v2_0.csv": [
        "term_id", "canonical_term", "category", "owner", "status",
        "definition", "prohibited_uses",
    ],
    "SKYWATCHER_LEGACY_ALIAS_REGISTRY_v2_0.csv": [
        "legacy_term", "canonical_replacement", "status", "confirmed_paths",
    ],
    "SKYWATCHER_THRESHOLD_REGISTRY_SEED_v2_0.csv": [
        "threshold_id", "owner", "current_value", "unit", "purpose", "status",
        "validation_artifact", "failure_behavior",
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
THRESHOLD_STATUSES = {"CANDIDATE", "CANDIDATE_PROJECT_GATE", "PROHIBITED"}


def _read_csv(name: str) -> list[dict[str, str]]:
    path = ARCH / name
    text = path.read_text(encoding="utf-8")
    assert "\ufffd" not in text, f"replacement character in {name}"
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == CSV_HEADERS[name]
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


def test_canonical_terms_and_alias_dispositions_are_unique() -> None:
    terms = _read_csv("SKYWATCHER_TERM_OWNERSHIP_MATRIX_v2_0.csv")
    assert len(terms) == 27
    assert all(row["owner"] and row["definition"] and row["prohibited_uses"] for row in terms)

    aliases = _read_csv("SKYWATCHER_LEGACY_ALIAS_REGISTRY_v2_0.csv")
    assert len(aliases) == 24
    assert {row["status"] for row in aliases} <= ALIAS_STATUSES
    assert all(row["canonical_replacement"] and row["confirmed_paths"] for row in aliases)


def test_thresholds_remain_non_executable() -> None:
    rows = _read_csv("SKYWATCHER_THRESHOLD_REGISTRY_SEED_v2_0.csv")
    assert len(rows) == 20
    assert {row["status"] for row in rows} <= THRESHOLD_STATUSES
    assert not ({"ACTIVE", "VALIDATED", "NORMATIVE", "EXECUTABLE"} & {row["status"] for row in rows})
    assert all(row["validation_artifact"] and row["failure_behavior"] for row in rows)


def test_migration_plan_authorization_boundary() -> None:
    rows = _read_csv("SKYWATCHER_PATH_LEVEL_MIGRATION_PLAN_v2_0.csv")
    assert len(rows) == 77
    g0 = [row for row in rows if row["approval_state"] == "AUTHORIZED_G0_ONLY"]
    blocked = [row for row in rows if row["approval_state"].startswith("BLOCKED")]
    assert len(g0) == 8
    assert len(blocked) == 69
    assert {row["path"] for row in g0} == AUTHORIZED_PATHS
    assert not [row for row in rows if row not in g0 and not row["approval_state"].startswith("BLOCKED")]


def test_freeze_manifest_recomputes_from_repository_bytes() -> None:
    manifest_path = ARCH / "SKYWATCHER_ONTOLOGY_FREEZE_MANIFEST_v2_0.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "skywatcher.ontology_freeze_manifest.v2.0"
    assert manifest["repository"] == "jotaele44/skywatcher-pr"
    assert manifest["base_commit"] == BASE_SHA
    assert manifest["authorized_paths"] == sorted(AUTHORIZED_PATHS)
    assert manifest["migration_plan_rows"] == 77
    assert manifest["g0_authorized_rows"] == 8
    assert manifest["g1_plus_blocked_rows"] == 69
    assert manifest["threshold_execution_authorized"] is False
    assert manifest["merge_authorized"] is False
    assert manifest["auto_merge_authorized"] is False

    records = manifest["artifact_records"]
    expected_record_paths = AUTHORIZED_PATHS - {
        "docs/architecture/SKYWATCHER_ONTOLOGY_FREEZE_MANIFEST_v2_0.json"
    }
    assert {record["path"] for record in records} == expected_record_paths
    assert len(records) == len(expected_record_paths)
    for record in records:
        path = REPO_ROOT / record["path"]
        assert path.is_file(), record["path"]
        assert record["size_bytes"] == path.stat().st_size
        assert record["sha256"] == _sha256(path)
