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
    invalidate_implications_for_artifacts,
    validate_domain_scope,
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
    db.execute("INSERT INTO swk_implication(implication_id,run_id,analysis_owner,domain_scope_json,implication_type,epistemic_class,delta_type,statement,scope_json,ruleset_version,dependency_sha256,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", ("i1","r1","FPIM",'{"scope_mode":"PHYSICAL","domains":["AIR"]}',"LOCAL","INFERENCE","NEW","A structured statement; no mission inferred","{}","v1",ZERO,"2026-09-30T00:00:00Z"))


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
    inp=dict(
        statement="route curvature measured",
        epistemic_class="COMPUTED",
        implication_type="LOCAL",
        delta_type="NO_MATERIAL_CHANGE",
        certification_state="PASS",
        validity_state="STALE",
        source_refs=["source:e1"],
        limitations=[],
        analysis_owner="FPIM",
        domain_scope={"scope_mode": "PHYSICAL", "domains": ["AIR"]},
    )
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

def test_hash_and_state_checks_fail_closed():
    with conn() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """
                INSERT INTO swk_knowledge_run(
                  run_id,input_manifest_sha256,ruleset_sha256,baseline_commit,started_utc
                ) VALUES('bad','NOT-A-HASH',?,?,?)
                """,
                (ZERO, "fixture", "now"),
            )
        seed(db)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """
                INSERT INTO swk_knowledge_state(
                  state_id,run_id,previous_state_id,source_manifestation_count,
                  unresolved_candidate_count,implication_count,contradiction_count,
                  state_manifest_sha256,certification_state,created_utc
                ) VALUES('state-a','r1','state-a',0,0,0,0,?,'OPEN','now')
                """,
                (ZERO,),
            )


def test_delta_vocabulary_is_closed():
    with conn() as db:
        seed(db)
        for state_id in ("s1", "s2"):
            db.execute(
                """
                INSERT INTO swk_knowledge_state(
                  state_id,run_id,source_manifestation_count,
                  unresolved_candidate_count,implication_count,contradiction_count,
                  state_manifest_sha256,certification_state,created_utc
                ) VALUES(?,?,0,0,0,0,?,'OPEN','now')
                """,
                (state_id, "r1", ZERO),
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """
                INSERT INTO swk_knowledge_delta(
                  delta_id,prior_state_id,new_state_id,dimension,delta_type,
                  before_json,after_json,explanation_json
                ) VALUES('d1','s1','s2','INVENTED_DIMENSION','NEW','{}','{}','{}')
                """
            )


def test_implication_lineage_rejects_transitive_cycle_and_updates():
    with conn() as db:
        seed(db)
        for implication_id in ("i2", "i3"):
            db.execute(
                """
                INSERT INTO swk_implication(
                  implication_id,run_id,analysis_owner,domain_scope_json,implication_type,epistemic_class,
                  delta_type,statement,scope_json,ruleset_version,dependency_sha256,created_utc
                ) VALUES(?, 'r1','FPIM','{"scope_mode":"PHYSICAL","domains":["AIR"]}',
                         'CORPUS','INFERENCE','REFINES',?,'{}','v1',?,'now')
                """,
                (implication_id, f"statement-{implication_id}", ZERO),
            )
        db.execute(
            "INSERT INTO swk_implication_lineage VALUES('i2','i1','DERIVED_FROM')"
        )
        db.execute(
            "INSERT INTO swk_implication_lineage VALUES('i3','i2','DERIVED_FROM')"
        )
        with pytest.raises(sqlite3.IntegrityError, match="cycle"):
            db.execute(
                "INSERT INTO swk_implication_lineage VALUES('i1','i3','DERIVED_FROM')"
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                """
                UPDATE swk_implication_lineage
                SET relation='WEAKENS'
                WHERE implication_id='i2' AND parent_implication_id='i1'
                """
            )

def test_artifact_invalidation_propagates_to_all_descendants():
    with conn() as db:
        seed(db)
        db.execute("INSERT INTO swk_implication_evidence VALUES('i1','e1','SUPPORT')")
        db.execute("UPDATE swk_implication SET certification_state='PASS' WHERE implication_id='i1'")
        for implication_id in ("i2", "i3"):
            db.execute(
                """
                INSERT INTO swk_implication(
                  implication_id,run_id,analysis_owner,domain_scope_json,implication_type,epistemic_class,
                  delta_type,statement,scope_json,ruleset_version,dependency_sha256,created_utc
                ) VALUES(?, 'r1','FPIM','{"scope_mode":"PHYSICAL","domains":["AIR"]}',
                         'CORPUS','INFERENCE','REFINES',?,'{}','v1',?,'now')
                """,
                (implication_id, f"statement-{implication_id}", ZERO),
            )
        db.execute("INSERT INTO swk_implication_lineage VALUES('i2','i1','DERIVED_FROM')")
        db.execute("INSERT INTO swk_implication_lineage VALUES('i3','i2','DERIVED_FROM')")

        affected = invalidate_implications_for_artifacts(db, ["e1"])
        assert affected == ["i1", "i2", "i3"]
        rows = db.execute(
            """
            SELECT implication_id,validity_state,certification_state
            FROM swk_implication
            ORDER BY implication_id
            """
        ).fetchall()
        assert rows == [
            ("i1", "STALE", "OPEN"),
            ("i2", "STALE", "OPEN"),
            ("i3", "STALE", "OPEN"),
        ]


def test_artifact_invalidation_no_match_is_noop():
    with conn() as db:
        seed(db)
        assert invalidate_implications_for_artifacts(db, ["unknown-artifact"]) == []
        assert db.execute(
            "SELECT validity_state FROM swk_implication WHERE implication_id='i1'"
        ).fetchone()[0] == "CURRENT"


def test_artifact_invalidation_rejects_scalar_string():
    with conn() as db:
        seed(db)
        with pytest.raises(ValueError, match="sequence of IDs"):
            invalidate_implications_for_artifacts(db, "e1")

def test_fr24_image_skill_declares_activation_gated_cumulative_handoff():
    skill = (
        REPO / "skills" / "skywatcher-fr24-image-analysis" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "Cumulative implication handoff — activation-gated" in skill
    assert "NO_MATERIAL_CHANGE" in skill
    assert "screenshot count is" in skill
    assert "never substituted for canonical event count" in skill
    assert "NOT_ENABLED" in skill

def test_pitirre_domain_scope_validation_is_explicit_and_non_normalizing():
    assert validate_domain_scope(
        {
            "scope_mode": "PHYSICAL",
            "domains": ["LAND"],
            "paths": [
                {
                    "domain": "LAND",
                    "subdomain": "TRANSPORT",
                    "network_type": "ROAD",
                }
            ],
        }
    ) == {
        "scope_mode": "PHYSICAL",
        "domains": ["LAND"],
        "paths": [
            {
                "domain": "LAND",
                "subdomain": "TRANSPORT",
                "network_type": "ROAD",
            }
        ],
    }
    with pytest.raises(ValueError, match="unsupported PITIRRE domain"):
        validate_domain_scope({"scope_mode": "PHYSICAL", "domains": ["road"]})
    with pytest.raises(ValueError, match="at least two domains"):
        validate_domain_scope({"scope_mode": "CROSS_DOMAIN", "domains": ["AIR"]})
    with pytest.raises(ValueError, match="cannot carry physical domains"):
        validate_domain_scope(
            {"scope_mode": "NON_PHYSICAL", "domains": ["AIR"]}
        )


def test_verbal_output_renders_domain_scope_without_promoting_mission():
    rendered = deterministic_verbal_output(
        {
            "statement": "Two adjudicated observations satisfy the configured window.",
            "epistemic_class": "COMPUTED",
            "implication_type": "CORPUS",
            "delta_type": "STRENGTHENS",
            "certification_state": "PASS",
            "validity_state": "CURRENT",
            "source_refs": ["source:a", "source:b"],
            "limitations": ["co-occurrence does not establish coordination"],
            "analysis_owner": "CORRIM",
            "domain_scope": {
                "scope_mode": "CROSS_DOMAIN",
                "domains": ["AIR", "WATER"],
            },
        }
    )
    assert "Owner: CORRIM" in rendered
    assert "Domain scope: AIR + WATER" in rendered
    assert "coordination" in rendered
    assert "mission" not in rendered.lower()

def test_sql_domain_scope_gate_rejects_invalid_tokens_and_cardinality():
    with conn() as db:
        seed(db)
        cases = [
            '{"scope_mode":"PHYSICAL","domains":["ROAD"]}',
            '{"scope_mode":"PHYSICAL","domains":["AIR","WATER"]}',
            '{"scope_mode":"CROSS_DOMAIN","domains":["AIR"]}',
            '{"scope_mode":"CROSS_DOMAIN","domains":["AIR","AIR"]}',
            '{"scope_mode":"NON_PHYSICAL","domains":["SPACE"]}',
        ]
        for index, domain_scope in enumerate(cases, start=1):
            with pytest.raises(sqlite3.IntegrityError, match="physical-domain"):
                db.execute(
                    """
                    INSERT INTO swk_implication(
                      implication_id,run_id,analysis_owner,domain_scope_json,
                      implication_type,epistemic_class,delta_type,statement,
                      scope_json,ruleset_version,dependency_sha256,created_utc
                    ) VALUES(?, 'r1','CORE',?,'LOCAL','INFERENCE','NEW',
                             'invalid domain scope fixture','{}','v1',?,'now')
                    """,
                    (f"bad-domain-{index}", domain_scope, ZERO),
                )

        db.execute(
            """
            INSERT INTO swk_implication(
              implication_id,run_id,analysis_owner,domain_scope_json,
              implication_type,epistemic_class,delta_type,statement,
              scope_json,ruleset_version,dependency_sha256,created_utc
            ) VALUES(
              'cross-ok','r1','CORRIM',
              '{"scope_mode":"CROSS_DOMAIN","domains":["AIR","WATER"]}',
              'CORPUS','INFERENCE','NEW','valid cross-domain fixture',
              '{}','v1',?,'now'
            )
            """,
            (ZERO,),
        )
        assert db.execute(
            "SELECT analysis_owner FROM swk_implication WHERE implication_id='cross-ok'"
        ).fetchone()[0] == "CORRIM"

