"""Self-contained synthetic gates for the opt-in implication sidecar.

Not a whole-repository, live-corpus, or production migration certificate.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from skywatcher.core.knowledge_implications import (
    classify_delta,
    dependency_digest,
    deterministic_verbal_output,
)

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "schemas" / "knowledge_implications_v1.sql"
ZERO = hashlib.sha256(b"").hexdigest()


def conn():
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA.read_text(encoding="utf8"))
    return db


def seed(db):
    db.execute("INSERT INTO swk_knowledge_run(run_id,input_manifest_sha256,ruleset_sha256,baseline_commit,started_utc) VALUES(?,?,?,?,?)", ("r1",ZERO,ZERO,"example-commit","2026-09-30T00:00:00Z"))
    db.execute("INSERT INTO swk_source_artifact(artifact_id,source_namespace,external_source_key_raw,source_kind,evidence_tier,visibility_class,created_utc) VALUES(?,?,?,?,?,?,?)", ("e1","RLSM_LOCAL","source:screenshot:1","SCREENSHOT","UNKNOWN","V0","2026-09-30T00:00:00Z"))
    db.execute("INSERT INTO swk_implication(implication_id,run_id,domain_owner,implication_type,epistemic_class,delta_type,statement,scope_json,ruleset_version,dependency_sha256,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)", ("i1","r1","FPIM","LOCAL","INFERENCE","NEW","A structured statement; no mission inferred","{}","v1",ZERO,"2026-09-30T00:00:00Z"))


def test_sql_idempotent_and_foreign_keys():
    with conn() as db:
        db.executescript(SCHEMA.read_text())
        assert db.execute("PRAGMA foreign_key_check").fetchall()==[]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO swk_implication_evidence VALUES('missing','missing','SUPPORT')")


def test_pass_fails_closed_without_bound_source():
    with conn() as db:
        seed(db)
        with pytest.raises(sqlite3.IntegrityError,match="supporting"):
            db.execute("UPDATE swk_implication SET certification_state='PASS' WHERE implication_id='i1'")
        db.execute("INSERT INTO swk_implication_evidence VALUES('i1','e1','SUPPORT')")
        db.execute("UPDATE swk_implication SET certification_state='PASS' WHERE implication_id='i1'")
        assert db.execute("SELECT certification_state FROM swk_implication").fetchone()[0]=='PASS'
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE swk_implication SET validity_state='INVALIDATED' WHERE implication_id='i1'")
        db.execute("UPDATE swk_implication SET validity_state='STALE', certification_state='OPEN' WHERE implication_id='i1'")


def test_no_source_ever_implies_canonical_event_count():
    b=dict(source_manifestation_count=1, unresolved_candidate_count=1, implication_count=0,
           contradiction_count=0,canonical_event_count=10,canonical_denominator_ref="MFL")
    a={**b, "source_manifestation_count":9,"canonical_event_count":11}
    # The MFL count may be claimed only after independent continuity certification.
    assert classify_delta(b,a)["canonical_event_count"] is None
    b.update(denominator_lineage_id="MFL-certified-series",
             continuity_receipt_sha256=ZERO,canonical_denominator_sha256="a"*64)
    a.update(denominator_lineage_id="MFL-certified-series",
             continuity_receipt_sha256=ZERO,canonical_denominator_sha256="b"*64)
    assert classify_delta(b,a)["canonical_event_count"]==1
    assert classify_delta(b,a)["source_manifestation_count"]==8
    assert classify_delta(b,{**a,"canonical_denominator_ref":"other"})["canonical_event_count"] is None


def test_dependency_hash_order_invariance_and_duplicate_rejection():
    a={"kind":"SOURCE","id":"x","version":"v1","role":"SUPPORT"}
    b={"kind":"SOURCE","id":"y","version":"v1","role":"CONTROL"}
    assert dependency_digest(ruleset_version="v1",dependencies=[a,b])==dependency_digest(ruleset_version="v1",dependencies=[b,a])
    with pytest.raises(ValueError,match="unique"):
        dependency_digest(ruleset_version="v1",dependencies=[a,a])


def test_no_invalid_verbal_promotion():
    inp=dict(statement="route curvature measured",epistemic_class="COMPUTED",implication_type="LOCAL",
             delta_type="NO_MATERIAL_CHANGE",certification_state="PASS",
             validity_state="STALE",source_refs=["source:e1"],limitations=[])
    with pytest.raises(ValueError,match="stale"):
        deterministic_verbal_output(inp)
    inp.update(validity_state="CURRENT",source_refs=[])
    with pytest.raises(ValueError,match="no source"):
        deterministic_verbal_output(inp)
    inp["source_refs"]=["source:e1"]
    assert "NO_MATERIAL_CHANGE" in deterministic_verbal_output(inp)


def test_no_naive_source_tier_or_gold_assumption():
    with conn() as db:
        seed(db)
        assert db.execute("SELECT evidence_tier FROM swk_source_artifact").fetchone()[0]=="UNKNOWN"
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE swk_source_artifact SET evidence_tier='GOLD_STANDARD' WHERE artifact_id='e1'")


def test_pass_cannot_lose_last_support_or_rewrite_source():
    with conn() as db:
        seed(db)
        db.execute("INSERT INTO swk_implication_evidence VALUES('i1','e1','SUPPORT')")
        db.execute("UPDATE swk_implication SET certification_state='PASS' WHERE implication_id='i1'")
        with pytest.raises(sqlite3.IntegrityError,match="PASS requires support"):
            db.execute("DELETE FROM swk_implication_evidence WHERE implication_id='i1'")
        with pytest.raises(sqlite3.IntegrityError,match="immutable"):
            db.execute("UPDATE swk_source_artifact SET source_kind='OTHER' WHERE artifact_id='e1'")
        db.execute("UPDATE swk_implication SET certification_state='OPEN',validity_state='STALE' WHERE implication_id='i1'")
        db.execute("DELETE FROM swk_implication_evidence WHERE implication_id='i1'")


def test_external_id_namespaces_dont_collapse():
    with conn() as db:
        seed(db)
        db.execute("INSERT INTO swk_subject_ref VALUES(?,?,?,?,?,?,?,?)",
                   ("r1","RLSM_SCREENSHOT","RLSM_LOCAL","17",ZERO,"UNRESOLVED","{}","now"))
        db.execute("INSERT INTO swk_subject_ref VALUES(?,?,?,?,?,?,?,?)",
                   ("r2","MFL_RECORD","MFL_SNAPSHOT","17",ZERO,"UNRESOLVED","{}","now"))
        assert db.execute("SELECT COUNT(*) FROM swk_subject_ref").fetchone()[0]==2
        assert db.execute("SELECT COUNT(*) FROM swk_subject_evidence").fetchone()[0]==0


def test_snapshot_hash_count_contradiction_fails_closed():
    before={k:0 for k in ("source_manifestation_count","unresolved_candidate_count","implication_count","contradiction_count")}
    after=dict(before)
    before.update(canonical_event_count=1,canonical_denominator_ref="MFL",canonical_denominator_sha256=ZERO,
                  denominator_lineage_id="MFL",continuity_receipt_sha256=ZERO)
    after.update(canonical_event_count=2,canonical_denominator_ref="MFL",canonical_denominator_sha256=ZERO,
                  denominator_lineage_id="MFL",continuity_receipt_sha256=ZERO)
    with pytest.raises(ValueError,match="identical denominator"):
        classify_delta(before,after)


def test_no_legacy_tables_modified():
    db=sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("CREATE TABLE flight_corpus_records(corpus_record_id INTEGER PRIMARY KEY, corpus_uid TEXT)")
    db.execute("INSERT INTO flight_corpus_records VALUES(1,'unchanged')")
    db.executescript(SCHEMA.read_text())
    assert db.execute("SELECT * FROM flight_corpus_records").fetchall()==[(1,'unchanged')]
    assert db.execute("PRAGMA foreign_key_check").fetchall()==[]


def test_pass_support_update_and_content_edit_rejected():
    with conn() as db:
        seed(db)
        db.execute("INSERT INTO swk_implication_evidence VALUES('i1','e1','SUPPORT')")
        db.execute("UPDATE swk_implication SET certification_state='PASS' WHERE implication_id='i1'")
        with pytest.raises(sqlite3.IntegrityError,match="support is immutable"):
            db.execute("UPDATE swk_implication_evidence SET evidence_role='CONTEXT' WHERE implication_id='i1'")
        with pytest.raises(sqlite3.IntegrityError,match="certified implication"):
            db.execute("UPDATE swk_implication SET statement='unbacked rewritten claim' WHERE implication_id='i1'")
