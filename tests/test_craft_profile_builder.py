"""CraftProfileBuilder aggregation, grading, persistence, and incrementality."""

import json
import sqlite3
from pathlib import Path

import jsonschema
import pytest

from skywatcher.fpim.craft_profile import (
    CraftProfileBuilder,
    ensure_tables,
    upsert_profile,
    write_json,
    write_snapshot,
)

REPO = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((REPO / "schemas" / "craft_profile.schema.json").read_text())


@pytest.fixture
def builder(rlsm_db):
    return CraftProfileBuilder(db_path=Path(rlsm_db))


def test_registrations_are_discovered(rlsm_db, builder):
    conn = sqlite3.connect(rlsm_db)
    assert builder.registrations(conn) == ["N5854Z", "N999XY"]
    conn.close()


def test_known_operator_profile(rlsm_db, builder):
    conn = sqlite3.connect(rlsm_db)
    p = builder.build_one(conn, "N5854Z")
    conn.close()
    jsonschema.validate(p.to_dict(), SCHEMA)
    assert p.data_source == "known_db"
    assert p.mission_is_authoritative is True
    assert p.owner == "Puerto Rico Electric Power Authority"
    assert p.profile_confidence_grade == "VERIFIED"
    assert p.total_observations == 10  # 5 days x 2 obs


def test_home_base_and_recurring_route(rlsm_db, builder):
    conn = sqlite3.connect(rlsm_db)
    p = builder.build_one(conn, "N5854Z")
    conn.close()
    assert p.home_base["iata"] == "SJU"
    assert p.home_base["facility_id"] == "airport_sju_tjsj"
    # 5 flight-days, one SJU->PSE cluster each => n_observed 5 over denominator 5.
    routes = {r["route_pattern"]: r for r in p.recurring_routes}
    assert "SJU → PSE" in routes
    assert routes["SJU → PSE"]["n_observed"] == 5
    assert routes["SJU → PSE"]["denominator"] == 5
    assert routes["SJU → PSE"]["confidence_grade"] == "HIGH"


def test_schedule_cells_and_denominator(rlsm_db, builder):
    conn = sqlite3.connect(rlsm_db)
    p = builder.build_one(conn, "N5854Z")
    conn.close()
    assert p.schedule["dow_hour_cells"], "expected cadence cells"
    assert p.schedule["denominator"] == p.schedule["lookback_weeks"]


def test_deduced_profile_has_no_authoritative_mission(rlsm_db, builder):
    conn = sqlite3.connect(rlsm_db)
    p = builder.build_one(conn, "N999XY")
    conn.close()
    jsonschema.validate(p.to_dict(), SCHEMA)
    assert p.mission_is_authoritative is False
    assert p.primary_mission is None
    # FAA registry gives owner; no georef => spatial coverage gap surfaced.
    assert p.owner == "SOME OWNER LLC"
    assert "home_base_no_georef" in p.coverage_gaps


def test_incremental_new_patterns_collapse(rlsm_db, builder):
    conn = sqlite3.connect(rlsm_db)
    ensure_tables(conn)
    first = builder.build_one(conn, "N5854Z")
    assert any(n["route_pattern"] == "SJU → PSE" for n in first.new_patterns)
    write_snapshot(conn, first)
    conn.commit()
    second = builder.build_one(conn, "N5854Z")
    conn.close()
    assert second.new_patterns == []  # already-known route no longer "new"


def test_persistence_roundtrip(rlsm_db, builder, tmp_path):
    conn = sqlite3.connect(rlsm_db)
    ensure_tables(conn)
    p = builder.build_one(conn, "N5854Z")
    upsert_profile(conn, p)
    # upsert twice must not duplicate (PRIMARY KEY registration).
    upsert_profile(conn, p)
    n = conn.execute("SELECT COUNT(*) FROM craft_profiles WHERE registration='N5854Z'").fetchone()[0]
    conn.close()
    assert n == 1
    out = write_json(p, tmp_path)
    reloaded = json.loads(out.read_text())
    assert reloaded["registration"] == "N5854Z"


def test_absent_db_is_graceful(tmp_path):
    missing = tmp_path / "nope.sqlite"
    b = CraftProfileBuilder(db_path=missing)
    # Registry indexes still load; building against a missing DB shouldn't be
    # attempted by callers — the driver guards it — but the builder itself must
    # not crash on construction.
    assert b.airport_index  # airport registry loaded from configs
