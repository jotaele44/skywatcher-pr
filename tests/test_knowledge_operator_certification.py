from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from skywatcher.core.knowledge_operator_certification import (
    OperatorCertificationError,
    certify_operator_package,
    discover_binding_candidates,
    materialize_review_sidecar,
    sha256_file,
    validate_binding_review,
    validate_gold_review,
)

REPO = Path(__file__).resolve().parents[1]


def _make_operator_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    rlsm = tmp_path / "rlsm.sqlite"
    mfl = tmp_path / "mfl.sqlite"
    corpus = tmp_path / "FR24_baseline"
    corpus.mkdir()

    conn = sqlite3.connect(rlsm)
    conn.executescript(
        """
        CREATE TABLE screenshots(
          screenshot_id INTEGER PRIMARY KEY,
          sha256 TEXT UNIQUE NOT NULL,
          filename TEXT NOT NULL,
          rel_path TEXT NOT NULL,
          ingest_status TEXT NOT NULL,
          ocr_status TEXT NOT NULL
        );
        CREATE TABLE source_manifestations(
          manifestation_id INTEGER PRIMARY KEY,
          rel_path TEXT,
          sha256 TEXT,
          screenshot_id INTEGER
        );
        CREATE TABLE aircraft_observations(
          aircraft_obs_id INTEGER PRIMARY KEY,
          screenshot_id INTEGER NOT NULL,
          registration TEXT,
          callsign TEXT,
          identity_status TEXT,
          observed_at TEXT NOT NULL
        );
        """
    )
    gold_rows = []
    for index in range(1, 301):
        filename = f"frame-{index:04d}.png"
        payload = f"fixture-frame-{index}".encode()
        sha = hashlib.sha256(payload).hexdigest()
        (corpus / filename).write_bytes(payload)
        rel_path = f"data/FR24_baseline/{filename}"
        conn.execute(
            "INSERT INTO screenshots VALUES(?,?,?,?,?,?)",
            (index, sha, filename, rel_path, "ok", "ok"),
        )
        gold_rows.append(
            {
                "screenshot_id": index,
                "screenshot_sha256": sha,
                "filename": filename,
                "labels": [],
                "annotator": f"annotator-{index % 3}",
                "reviewed_by": f"reviewer-{(index % 3) + 10}",
            }
        )
    conn.execute(
        """
        INSERT INTO aircraft_observations
        VALUES(1,1,'N111AA','CALL111','confirmed','2026-09-01T10:00:00Z')
        """
    )
    conn.execute(
        """
        INSERT INTO aircraft_observations
        VALUES(2,2,'N222BB','CALL222','confirmed','2026-09-02T11:00:00Z')
        """
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(mfl)
    conn.executescript(
        """
        CREATE TABLE flight_corpus_snapshots(
          snapshot_id INTEGER PRIMARY KEY,
          source_kind TEXT,
          source_sha256 TEXT
        );
        CREATE TABLE flight_corpus_records(
          corpus_record_id INTEGER PRIMARY KEY,
          corpus_uid TEXT NOT NULL,
          snapshot_id INTEGER NOT NULL,
          source_flight_id_raw TEXT,
          callsign_raw TEXT,
          start_time_utc TEXT,
          end_time_utc TEXT
        );
        CREATE TABLE flight_source_manifestations(
          manifestation_id INTEGER PRIMARY KEY,
          corpus_record_id INTEGER NOT NULL,
          source_folder_raw TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO flight_corpus_snapshots VALUES(1,'fixture',?)",
        ("a" * 64,),
    )
    conn.execute(
        """
        INSERT INTO flight_corpus_records
        VALUES(1,'mfl:1',1,'flight-111','CALL111',
               '2026-09-01T09:50:00Z','2026-09-01T10:20:00Z')
        """
    )
    conn.execute(
        """
        INSERT INTO flight_corpus_records
        VALUES(2,'mfl:2',1,'flight-222','CALL222',
               '2026-09-02T10:50:00Z','2026-09-02T11:20:00Z')
        """
    )
    conn.execute(
        "INSERT INTO flight_source_manifestations VALUES(1,1,'N111AA')"
    )
    conn.execute(
        "INSERT INTO flight_source_manifestations VALUES(2,2,'N222BB')"
    )
    conn.commit()
    conn.close()

    gold = tmp_path / "gold_sample_300.jsonl"
    gold.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in gold_rows
        ),
        encoding="utf-8",
    )
    return rlsm, mfl, corpus, gold


def _review(candidates: list[dict]) -> list[dict]:
    reviewed = [dict(row) for row in candidates]
    assert len(reviewed) == 2
    first, second = reviewed
    first["decision"] = "SAME_EVENT"
    first["decision_basis"] = ["DISPLAYED_SOURCE_FLIGHT_ID"]
    first["independent_evidence_refs"] = ["screen:displayed-flight-id:flight-111"]
    first["reviewed_by"] = "binding-reviewer"
    first["reviewed_at"] = "2026-10-03T12:00:00Z"
    first["notes"] = "positive control"

    second["decision"] = "DIFFERENT_EVENT"
    second["decision_basis"] = ["DIFFERENT_SOURCE_FLIGHT_ID"]
    second["independent_evidence_refs"] = ["screen:displayed-flight-id:other"]
    second["reviewed_by"] = "binding-reviewer"
    second["reviewed_at"] = "2026-10-03T12:05:00Z"
    second["notes"] = "negative control"
    return reviewed


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def test_gold_review_requires_exact_independent_300(tmp_path: Path) -> None:
    rlsm, _mfl, _corpus, gold = _make_operator_fixture(tmp_path)
    metrics, resolved = validate_gold_review(rlsm, gold)
    assert metrics["records"] == 300
    assert metrics["expected_records"] == 300
    assert metrics["unique_resolved_records"] == 300
    assert metrics["source_byte_failures"] == 0
    assert metrics["error_count"] == 0
    assert metrics["status"] == "PASS"
    assert len(resolved) == 300

    rows = gold.read_text(encoding="utf-8").splitlines()
    row = json.loads(rows[0])
    row["reviewed_by"] = row["annotator"]
    rows[0] = json.dumps(row)
    bad = tmp_path / "bad-gold.jsonl"
    bad.write_text("\n".join(rows) + "\n", encoding="utf-8")
    metrics, _ = validate_gold_review(rlsm, bad)
    assert metrics["status"] == "FAIL"
    assert metrics["error_count"] == 1


def test_candidate_union_is_bounded_and_discovery_only(tmp_path: Path) -> None:
    rlsm, mfl, _corpus, gold = _make_operator_fixture(tmp_path)
    candidates, manifest = discover_binding_candidates(rlsm, mfl, gold)
    assert len(candidates) == 2
    assert manifest["candidate_count"] == 2
    assert manifest["gold_unique_resolved_records"] == 300
    assert manifest["candidate_identity_rule"] == "DISCOVERY_ONLY_NOT_EVENT_IDENTITY"
    assert {tuple(row["candidate_basis"]) for row in candidates} == {
        ("CALLSIGN_EXACT_CASEFOLD", "REGISTRATION_FOLDER_EXACT_CASEFOLD"),
    }
    assert all(row["decision"] == "UNREVIEWED" for row in candidates)


def test_same_event_requires_independent_strong_basis(tmp_path: Path) -> None:
    rlsm, mfl, _corpus, gold = _make_operator_fixture(tmp_path)
    candidates, _ = discover_binding_candidates(rlsm, mfl, gold)
    reviewed = _review(candidates)
    reviewed[0]["decision_basis"] = ["CALLSIGN_ONLY"]
    review = tmp_path / "review.jsonl"
    _write_jsonl(review, reviewed)

    metrics, errors = validate_binding_review(review, candidates)
    assert metrics["status"] == "FAIL"
    assert {
        error["kind"] for error in errors
    } >= {"same_event_without_independent_strong_basis"}


def test_review_requires_positive_and_negative_controls(tmp_path: Path) -> None:
    rlsm, mfl, _corpus, gold = _make_operator_fixture(tmp_path)
    candidates, _ = discover_binding_candidates(rlsm, mfl, gold)
    reviewed = _review(candidates)
    reviewed[1]["decision"] = "UNRESOLVED"
    reviewed[1]["decision_basis"] = []
    reviewed[1]["independent_evidence_refs"] = []
    review = tmp_path / "review.jsonl"
    _write_jsonl(review, reviewed)

    metrics, errors = validate_binding_review(review, candidates)
    assert errors == []
    assert metrics["status"] == "BLOCKED"
    assert metrics["positive_and_negative_controls_present"] is False


def test_sidecar_materialization_does_not_claim_event_count(tmp_path: Path) -> None:
    rlsm, mfl, _corpus, gold = _make_operator_fixture(tmp_path)
    candidates, _ = discover_binding_candidates(rlsm, mfl, gold)
    reviewed = _review(candidates)
    review = tmp_path / "review.jsonl"
    _write_jsonl(review, reviewed)
    metrics, errors = validate_binding_review(review, candidates)
    assert metrics["status"] == "PASS"
    assert errors == []

    sidecar = tmp_path / "sidecar.sqlite"
    result = materialize_review_sidecar(
        sidecar_path=sidecar,
        schema_sql=(
            REPO / "schemas" / "knowledge_implications_v1.sql"
        ).read_text(encoding="utf-8"),
        reviewed_rows=reviewed,
        rlsm_db_sha256=sha256_file(rlsm),
        mfl_db_sha256=sha256_file(mfl),
        gold_sha256=sha256_file(gold),
        review_sha256=sha256_file(review),
        git_sha="a" * 40,
        package_status="PASS",
    )
    assert result["canonical_event_count_claimed"] is False
    conn = sqlite3.connect(sidecar)
    assert conn.execute(
        "SELECT canonical_event_count FROM swk_knowledge_state"
    ).fetchone()[0] is None
    assert conn.execute(
        "SELECT COUNT(*) FROM swk_implication WHERE certification_state='PASS'"
    ).fetchone()[0] == 2
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_full_operator_package_freezes_sources_and_writes_scratch_only(
    tmp_path: Path,
) -> None:
    rlsm, mfl, corpus, gold = _make_operator_fixture(tmp_path)
    candidates, _ = discover_binding_candidates(rlsm, mfl, gold)
    review = tmp_path / "review.jsonl"
    _write_jsonl(review, _review(candidates))
    before = (sha256_file(rlsm), sha256_file(mfl), sha256_file(gold))

    def fake_audit(**kwargs):
        out = Path(kwargs["outputs_dir"])
        out.mkdir(parents=True, exist_ok=True)
        return {
            "certification_status": "PASS",
            "required_gates": ["fixture"],
            "gates": {"fixture": {"status": "PASS"}},
            "error_count": 0,
        }

    report = certify_operator_package(
        repo_root=REPO,
        rlsm_db=rlsm,
        mfl_db=mfl,
        corpus_root=corpus,
        gold_path=gold,
        review_path=review,
        output_dir=tmp_path / "out",
        audit_runner=fake_audit,
    )
    assert report["certification_status"] == "PASS"
    assert report["claims"]["canonical_event_count_changed"] is False
    assert report["claims"]["canonical_mfl_mutation_authorized"] is False
    assert report["claims"]["migration_0004_registered"] is False
    assert Path(report["sidecar"]["path"]).is_file()
    assert before == (sha256_file(rlsm), sha256_file(mfl), sha256_file(gold))


def test_gold_identity_conflict_fails_closed(tmp_path: Path) -> None:
    rlsm, _mfl, _corpus, gold = _make_operator_fixture(tmp_path)
    rows = [json.loads(line) for line in gold.read_text().splitlines()]
    rows[0]["screenshot_sha256"] = rows[1]["screenshot_sha256"]
    _write_jsonl(gold, rows)
    metrics, _ = validate_gold_review(rlsm, gold)
    assert metrics["status"] == "FAIL"


def test_missing_operator_database_fails_closed(tmp_path: Path) -> None:
    gold = tmp_path / "present.jsonl"
    gold.write_text("", encoding="utf-8")
    with pytest.raises(OperatorCertificationError, match="database not found"):
        validate_gold_review(tmp_path / "missing.sqlite", gold)

def test_gold_source_byte_mutation_fails_when_corpus_is_verified(tmp_path: Path) -> None:
    rlsm, _mfl, corpus, gold = _make_operator_fixture(tmp_path)
    metrics, _ = validate_gold_review(rlsm, gold, corpus_root=corpus)
    assert metrics["status"] == "PASS"
    assert metrics["source_bytes_verified"] == 300
    assert metrics["source_manifest_sha256"]

    (corpus / "frame-0001.png").write_bytes(b"mutated")
    metrics, _ = validate_gold_review(rlsm, gold, corpus_root=corpus)
    assert metrics["status"] == "FAIL"
    assert metrics["source_byte_failures"] == 1


def test_blocked_package_cannot_contain_pass_implications(tmp_path: Path) -> None:
    rlsm, mfl, _corpus, gold = _make_operator_fixture(tmp_path)
    candidates, _ = discover_binding_candidates(rlsm, mfl, gold)
    reviewed = _review(candidates)
    review = tmp_path / "review.jsonl"
    _write_jsonl(review, reviewed)

    sidecar = tmp_path / "blocked-sidecar.sqlite"
    materialize_review_sidecar(
        sidecar_path=sidecar,
        schema_sql=(
            REPO / "schemas" / "knowledge_implications_v1.sql"
        ).read_text(encoding="utf-8"),
        reviewed_rows=reviewed,
        rlsm_db_sha256=sha256_file(rlsm),
        mfl_db_sha256=sha256_file(mfl),
        gold_sha256=sha256_file(gold),
        review_sha256=sha256_file(review),
        git_sha="b" * 40,
        package_status="BLOCKED",
    )
    conn = sqlite3.connect(sidecar)
    assert conn.execute(
        "SELECT COUNT(*) FROM swk_implication WHERE certification_state='PASS'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM swk_subject_ref WHERE identity_state='PASS'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT certification_state FROM swk_knowledge_state"
    ).fetchone()[0] == "BLOCKED"
    conn.close()

def test_binding_review_json_schema_rejects_unknown_fields(tmp_path: Path) -> None:
    rlsm, mfl, _corpus, gold = _make_operator_fixture(tmp_path)
    candidates, _ = discover_binding_candidates(rlsm, mfl, gold)
    reviewed = _review(candidates)
    reviewed[0]["invented_field"] = "must fail closed"
    review = tmp_path / "review-schema-invalid.jsonl"
    _write_jsonl(review, reviewed)

    metrics, errors = validate_binding_review(review, candidates)
    assert metrics["status"] == "FAIL"
    assert any(error["kind"] == "review_schema_error" for error in errors)


def test_failed_review_does_not_materialize_sidecar_and_report_freezes_outputs(
    tmp_path: Path,
) -> None:
    rlsm, mfl, corpus, gold = _make_operator_fixture(tmp_path)
    candidates, _ = discover_binding_candidates(rlsm, mfl, gold)
    reviewed = _review(candidates)
    reviewed[0]["decision_basis"] = ["CALLSIGN_ONLY"]
    review = tmp_path / "review-invalid.jsonl"
    _write_jsonl(review, reviewed)

    def fake_audit(**kwargs):
        out = Path(kwargs["outputs_dir"])
        out.mkdir(parents=True, exist_ok=True)
        return {
            "certification_status": "PASS",
            "required_gates": ["fixture"],
            "gates": {"fixture": {"status": "PASS"}},
            "error_count": 0,
        }

    output = tmp_path / "failed-out"
    report = certify_operator_package(
        repo_root=REPO,
        rlsm_db=rlsm,
        mfl_db=mfl,
        corpus_root=corpus,
        gold_path=gold,
        review_path=review,
        output_dir=output,
        audit_runner=fake_audit,
    )
    assert report["certification_status"] == "FAIL"
    assert report["sidecar"]["status"] == "NOT_MATERIALIZED"
    assert report["outputs"]["sidecar"] is None
    assert not (output / "operator_sidecar.sqlite").exists()
    frozen = Path(report["outputs"]["frozen_review"])
    assert frozen.is_file()
    assert frozen.read_bytes() == review.read_bytes()

    persisted = json.loads(
        (output / "operator_certification_report.json").read_text(encoding="utf-8")
    )
    assert persisted["outputs"] == report["outputs"]
    assert persisted["sidecar"]["status"] == "NOT_MATERIALIZED"

def test_scratch_sidecar_reuses_identical_inputs_but_preserves_changed_run(
    tmp_path: Path,
) -> None:
    rlsm, mfl, _corpus, gold = _make_operator_fixture(tmp_path)
    candidates, _ = discover_binding_candidates(rlsm, mfl, gold)
    reviewed = _review(candidates)
    review = tmp_path / "review.jsonl"
    _write_jsonl(review, reviewed)
    kwargs = {
        "sidecar_path": tmp_path / "sidecar.sqlite",
        "schema_sql": (
            REPO / "schemas" / "knowledge_implications_v1.sql"
        ).read_text(encoding="utf-8"),
        "reviewed_rows": reviewed,
        "rlsm_db_sha256": sha256_file(rlsm),
        "mfl_db_sha256": sha256_file(mfl),
        "gold_sha256": sha256_file(gold),
        "review_sha256": sha256_file(review),
        "git_sha": "c" * 40,
        "package_status": "PASS",
    }
    first = materialize_review_sidecar(**kwargs)
    second = materialize_review_sidecar(**kwargs)
    assert first["reused_identical_inputs"] is False
    assert second["reused_identical_inputs"] is True
    assert first["sha256"] == second["sha256"]

    changed = dict(kwargs)
    changed["review_sha256"] = "d" * 64
    with pytest.raises(
        OperatorCertificationError,
        match="already exists for different inputs",
    ):
        materialize_review_sidecar(**changed)
    assert Path(kwargs["sidecar_path"]).is_file()
    assert sha256_file(Path(kwargs["sidecar_path"])) == first["sha256"]

def test_zero_unresolved_residue_required_for_operator_pass(tmp_path: Path) -> None:
    rlsm, mfl, _corpus, gold = _make_operator_fixture(tmp_path)
    candidates, _ = discover_binding_candidates(rlsm, mfl, gold)
    third = json.loads(json.dumps(candidates[0]))
    third["candidate_id"] = "f" * 64
    candidates = [*candidates, third]

    reviewed = _review(candidates[:2])
    unresolved = json.loads(json.dumps(third))
    unresolved["decision"] = "UNRESOLVED"
    unresolved["decision_basis"] = []
    unresolved["independent_evidence_refs"] = []
    unresolved["reviewed_by"] = "binding-reviewer"
    unresolved["reviewed_at"] = "2026-10-03T12:10:00Z"
    unresolved["notes"] = "insufficient independent evidence"
    reviewed.append(unresolved)

    review = tmp_path / "review-with-residue.jsonl"
    _write_jsonl(review, reviewed)
    metrics, errors = validate_binding_review(review, candidates)
    assert errors == []
    assert metrics["positive_and_negative_controls_present"] is True
    assert metrics["unresolved"] == 1
    assert metrics["status"] == "BLOCKED"

