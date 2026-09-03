"""QueryEngine intent resolution + grounded answers over built profiles."""

import sqlite3
from pathlib import Path

import pytest

from skywatcher.fpim.craft_profile import (
    CraftProfileBuilder,
    ensure_tables,
    upsert_profile,
    write_snapshot,
)
from skywatcher.query.engine import QueryEngine


@pytest.fixture
def profiled_db(rlsm_db):
    """rlsm_db with craft_profiles populated (query reads that table)."""
    conn = sqlite3.connect(rlsm_db)
    ensure_tables(conn)
    b = CraftProfileBuilder(db_path=Path(rlsm_db))
    for reg in b.registrations(conn):
        p = b.build_one(conn, reg)
        upsert_profile(conn, p)
        write_snapshot(conn, p)
    conn.commit()
    conn.close()
    return rlsm_db


@pytest.fixture
def engine(profiled_db):
    return QueryEngine(db_path=Path(profiled_db))


def test_profiles_load_from_db(engine):
    assert set(engine.profiles()) == {"N5854Z", "N999XY"}


def test_schedule_intent(engine):
    a = engine.answer("what is the regular schedule for N5854Z?")
    assert a.intent == "SCHEDULE"
    assert a.craft == "N5854Z"
    assert a.facts
    assert a.confidence_grade in ("MODERATE", "HIGH", "VERIFIED")


def test_home_base_intent(engine):
    a = engine.answer("where is N5854Z based?")
    assert a.intent == "HOME_BASE"
    assert any("Luis Muñoz Marín" in f or "SJU" in f for f in a.facts)
    assert a.citations[0]["field"] == "home_base"


def test_preferred_lzs_intent(engine):
    a = engine.answer("which landing zones does N5854Z prefer?")
    assert a.intent == "PREFERRED_LZS"
    assert a.facts


def test_recurring_routes_intent(engine):
    a = engine.answer("what routes recur for N5854Z?")
    assert a.intent == "RECURRING_ROUTES"
    assert any("SJU → PSE" in f for f in a.facts)


def test_fleet_summary_intent(engine):
    a = engine.answer("how many aircraft are profiled?")
    assert a.intent == "FLEET_SUMMARY"
    assert any("2 aircraft profiled" in f for f in a.facts)


def test_deduced_profile_answer_carries_no_intent_caveat(engine):
    a = engine.answer("tell me about N999XY")
    assert a.intent == "PROFILE"
    assert any("not inferred" in c for c in a.caveats)


def test_unknown_craft_is_honest(engine):
    a = engine.answer("schedule for N00000")
    assert a.facts == []
    assert a.caveats


def test_co_occurrence_defers_honestly(engine):
    a = engine.answer("when do N5854Z and N999XY fly together?")
    assert a.intent == "CO_OCCURRENCE"
    assert a.facts == []
    assert any("network_graph" in c for c in a.caveats)


def test_answer_text_renders(engine):
    text = engine.answer("home base for N5854Z").to_text()
    assert "Confidence:" in text
    assert "candidate" in text
