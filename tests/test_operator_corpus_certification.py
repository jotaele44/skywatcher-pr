from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from skywatcher.core import operator_corpus_certification as occ

COMMIT = "a" * 40


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_rlsm(repo_root: Path) -> tuple[Path, Path]:
    db_path = repo_root / "rlsm.sqlite"
    corpus = repo_root / "data" / "FR24_baseline"
    corpus.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE screenshots(
          screenshot_id INTEGER PRIMARY KEY,
          sha256 TEXT NOT NULL,
          filename TEXT NOT NULL,
          rel_path TEXT NOT NULL,
          filename_ts TEXT,
          ingest_status TEXT NOT NULL
        );
        CREATE TABLE aircraft_observations(
          aircraft_obs_id INTEGER PRIMARY KEY,
          screenshot_id INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
          callsign TEXT,
          registration TEXT
        );
        """
    )
    for index in range(1, 301):
        path = corpus / f"shot-{index:03d}.png"
        path.write_bytes(f"fixture-{index}".encode())
        digest = _sha(path)
        conn.execute(
            """
            INSERT INTO screenshots(
              screenshot_id,sha256,filename,rel_path,filename_ts,ingest_status
            ) VALUES(?,?,?,?,?,'ok')
            """,
            (
                index,
                digest,
                path.name,
                path.relative_to(repo_root).as_posix(),
                f"2026-09-01T12:{index % 60:02d}:00",
            ),
        )
    conn.execute(
        """
        INSERT INTO aircraft_observations(
          aircraft_obs_id,screenshot_id,callsign,registration
        ) VALUES(1,1,'TEST123','NTEST1')
        """
    )
    conn.commit()
    conn.close()
    return db_path, corpus


def _make_gold(repo_root: Path, rlsm_db: Path) -> Path:
    conn = sqlite3.connect(rlsm_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT screenshot_id,sha256,filename FROM screenshots ORDER BY screenshot_id"
    ).fetchall()
    conn.close()
    path = repo_root / "gold_sample_300.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    {
                        "screenshot_id": row["screenshot_id"],
                        "screenshot_sha256": row["sha256"],
                        "filename": row["filename"],
                        "labels": [],
                        "annotator": "annotator-A",
                        "reviewed_by": "reviewer-B",
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    return path


def _make_mfl(repo_root: Path) -> Path:
    path = repo_root / "mfl.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE schema_version(
          version INTEGER PRIMARY KEY,
          description TEXT NOT NULL,
          applied_at TEXT NOT NULL
        );
        INSERT INTO schema_version VALUES(3,'fixture','now');
        CREATE TABLE flight_corpus_snapshots(
          snapshot_id INTEGER PRIMARY KEY,
          source_sha256 TEXT
        );
        INSERT INTO flight_corpus_snapshots VALUES(1,'aaa');
        CREATE TABLE flight_corpus_records(
          corpus_record_id INTEGER PRIMARY KEY,
          snapshot_id INTEGER NOT NULL,
          corpus_uid TEXT NOT NULL,
          source_flight_id_raw TEXT,
          callsign_raw TEXT,
          start_time_utc TEXT,
          end_time_utc TEXT
        );
        INSERT INTO flight_corpus_records VALUES(
          10,1,'uid-10','abc123','TEST123','2026-09-01T12:00:00Z','2026-09-01T12:10:00Z'
        );
        INSERT INTO flight_corpus_records VALUES(
          11,1,'uid-11','def456','TEST123','2026-09-02T12:00:00Z','2026-09-02T12:10:00Z'
        );
        CREATE TABLE flight_source_manifestations(
          manifestation_id INTEGER PRIMARY KEY,
          corpus_record_id INTEGER NOT NULL,
          source_kind TEXT
        );
        """
    )
    conn.commit()
    conn.close()
    return path


def _fake_audit(*, outputs_dir: Path, **_: object) -> dict:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    path = outputs_dir / "screenshot_intelligence_audit.json"
    report = {
        "certification_status": "PASS",
        "required_gates": ["fixture_gate"],
        "gates": {"fixture_gate": {"status": "PASS"}},
        "outputs": {"json": path.as_posix()},
    }
    path.write_text(json.dumps(report), encoding="utf-8")
    return report


def _prepared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    rlsm, corpus = _make_rlsm(repo_root)
    gold = _make_gold(repo_root, rlsm)
    mfl = _make_mfl(repo_root)
    monkeypatch.setattr(occ, "_git_head", lambda _: COMMIT)
    monkeypatch.setattr(occ, "_run_rlsm_audit", _fake_audit)
    out = repo_root / "operator-package"
    source_hashes = (_sha(rlsm), _sha(mfl))
    manifest = occ.prepare_package(
        repo_root=repo_root,
        rlsm_db=rlsm,
        mfl_db=mfl,
        corpus_root=corpus,
        gold_path=gold,
        output_dir=out,
        expected_commit=COMMIT,
    )
    return repo_root, rlsm, mfl, out, manifest, source_hashes


def test_prepare_is_read_only_and_builds_full_candidate_union(tmp_path, monkeypatch):
    repo_root, rlsm, mfl, out, manifest, source_hashes = _prepared(
        tmp_path, monkeypatch
    )
    assert manifest["preparation_status"] == "READY_FOR_ADJUDICATION"
    assert manifest["migration_0004_registered"] is False
    assert manifest["mfl_contract"]["schema_version"] == 3
    assert manifest["candidate_counts"]["candidate_pairs"] == 2
    assert _sha(rlsm) == source_hashes[0]
    assert _sha(mfl) == source_hashes[1]

    packet = occ._read_jsonl(out / "identity_candidates.jsonl")
    assert len(packet) == 1
    assert packet[0]["candidate_count"] == 2
    assert {
        item["mfl_corpus_record_id"]
        if "mfl_corpus_record_id" in item
        else item["corpus_record_id"]
        for item in packet[0]["candidate_records"]
    } == {10, 11}
    assert all(
        item["association_status"] == "CANDIDATE_NOT_IDENTITY"
        for item in packet[0]["candidate_records"]
    )
    assert (out / "inputs" / "rlsm.snapshot.sqlite").is_file()
    assert (out / "inputs" / "mfl.snapshot.sqlite").is_file()
    assert repo_root.is_dir()


def test_verify_positive_and_negative_controls_closes_bounded_denominator(
    tmp_path, monkeypatch
):
    repo_root, _, _, out, _, _ = _prepared(tmp_path, monkeypatch)
    rows = occ._read_jsonl(out / "adjudication_template.jsonl")
    assert len(rows) == 2
    rows[0].update(
        review_state="REVIEWED",
        decision="SAME_EVENT",
        identity_basis=["AUTHORITATIVE_SOURCE_BINDING"],
        evidence_refs=["review://primary-source/positive"],
        control_role="POSITIVE_CONTROL",
        reviewer_id="reviewer-C",
    )
    rows[1].update(
        review_state="REVIEWED",
        decision="DISTINCT_EVENT",
        identity_basis=["DISJOINT_TIME_INTERVALS"],
        evidence_refs=["review://time-series/negative"],
        control_role="NEGATIVE_CONTROL",
        reviewer_id="reviewer-C",
    )
    adjudications = repo_root / "adjudications.jsonl"
    occ._write_jsonl(adjudications, rows)

    receipt = occ.verify_adjudications(
        repo_root=repo_root,
        package_dir=out,
        adjudications_path=adjudications,
        expected_commit=COMMIT,
    )
    assert receipt["certification_status"] == "PASS"
    assert receipt["same_event"] == 1
    assert receipt["distinct_event"] == 1
    assert receipt["unresolved"] == 0
    assert receipt["canonical_mfl_mutation_authorized"] is False
    bindings = occ._read_jsonl(out / "certified_bindings.jsonl")
    assert len(bindings) == 1
    assert bindings[0]["canonical_mfl_mutation_authorized"] is False


def test_verify_rejects_weak_same_event_basis(tmp_path, monkeypatch):
    repo_root, _, _, out, _, _ = _prepared(tmp_path, monkeypatch)
    rows = occ._read_jsonl(out / "adjudication_template.jsonl")
    for row in rows:
        row.update(
            review_state="REVIEWED",
            decision="DISTINCT_EVENT",
            identity_basis=["DISJOINT_TIME_INTERVALS"],
            evidence_refs=["review://negative"],
            control_role="NEGATIVE_CONTROL",
            reviewer_id="reviewer-C",
        )
    rows[0].update(
        decision="SAME_EVENT",
        identity_basis=["EXACT_CALLSIGN"],
        evidence_refs=["review://callsign-only"],
        control_role="POSITIVE_CONTROL",
    )
    adjudications = repo_root / "weak.jsonl"
    occ._write_jsonl(adjudications, rows)
    receipt = occ.verify_adjudications(
        repo_root=repo_root,
        package_dir=out,
        adjudications_path=adjudications,
        expected_commit=COMMIT,
    )
    assert receipt["certification_status"] == "FAIL"
    assert any(
        item["reason"] == "same_event_lacks_strong_identity_basis"
        for item in receipt["errors"]
    )


def test_verify_preserves_unresolved_as_provisional(tmp_path, monkeypatch):
    repo_root, _, _, out, _, _ = _prepared(tmp_path, monkeypatch)
    rows = occ._read_jsonl(out / "adjudication_template.jsonl")
    rows[0].update(
        review_state="REVIEWED",
        decision="SAME_EVENT",
        identity_basis=["INDEPENDENT_EVENT_ID_BINDING"],
        evidence_refs=["review://positive"],
        control_role="POSITIVE_CONTROL",
        reviewer_id="reviewer-C",
    )
    rows[1].update(
        review_state="REVIEWED",
        decision="UNRESOLVED",
        identity_basis=[],
        evidence_refs=[],
        control_role="NONE",
        reviewer_id="reviewer-C",
        notes="top evidence remains tied",
    )
    # Add an independently evidenced negative control without changing the candidate
    # denominator by swapping the second row for a reviewed negative, then retain a
    # third unresolved pair in a dedicated three-candidate fixture would be required.
    # Here the missing negative control is correctly BLOCKED, never PASS.
    adjudications = repo_root / "unresolved.jsonl"
    occ._write_jsonl(adjudications, rows)
    receipt = occ.verify_adjudications(
        repo_root=repo_root,
        package_dir=out,
        adjudications_path=adjudications,
        expected_commit=COMMIT,
    )
    assert receipt["certification_status"] == "BLOCKED"
    assert receipt["unresolved"] == 1
    assert receipt["negative_controls"] == 0


def test_prepare_blocks_when_migration_0004_is_registered(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    rlsm, corpus = _make_rlsm(repo_root)
    gold = _make_gold(repo_root, rlsm)
    mfl = _make_mfl(repo_root)
    monkeypatch.setattr(occ, "_git_head", lambda _: COMMIT)
    monkeypatch.setattr(occ, "_run_rlsm_audit", _fake_audit)

    original = list(occ.migrations.MIGRATIONS)
    fake = occ.migrations.Migration(4, "forbidden", lambda conn: None)
    monkeypatch.setattr(occ.migrations, "MIGRATIONS", [*original, fake])
    monkeypatch.setattr(occ.migrations, "LATEST_VERSION", 4)

    with pytest.raises(occ.OperatorCertificationError, match="0004 NOT_REGISTERED"):
        occ.prepare_package(
            repo_root=repo_root,
            rlsm_db=rlsm,
            mfl_db=mfl,
            corpus_root=corpus,
            gold_path=gold,
            output_dir=repo_root / "out",
            expected_commit=COMMIT,
        )
