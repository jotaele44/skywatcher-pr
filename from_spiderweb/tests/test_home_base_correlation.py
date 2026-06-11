"""Tests for home-base correlation: resting-spot deduction + fleet co-location."""

import sqlite3

import pytest

from pipeline.home_base_correlation import (
    FleetColocationAnalyzer,
    HomeBaseDeducer,
)

# Canonical PR base coordinates used throughout the fixture.
BORINQUEN = (18.4948, -67.1294)
SJU = (18.4373, -66.0018)
ISLA_GRANDE = (18.4519, -66.1198)
FURA = (18.4500, -66.0500)
PALO_SECO = (18.0523, -67.0258)


def _schema(conn):
    conn.execute("""
        CREATE TABLE flights (
            flight_id TEXT PRIMARY KEY, callsign TEXT, aircraft_type TEXT,
            operator TEXT, origin_airport TEXT, destination_airport TEXT,
            origin_lat REAL, origin_lon REAL, dest_lat REAL, dest_lon REAL,
            takeoff_time TEXT, landing_time TEXT, flight_duration_minutes INTEGER,
            max_altitude_ft INTEGER, avg_speed_mph REAL, mission_type TEXT,
            num_screenshots INTEGER
        )
    """)


def _flight(conn, fid, callsign, origin, dest, takeoff, landing):
    conn.execute(
        "INSERT INTO flights VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (fid, callsign, "", "", "", "",
         origin[0], origin[1], dest[0], dest[1],
         takeoff, landing, 90, 3000, 120.0, "", 1),
    )


@pytest.fixture
def home_base_db(tmp_path):
    """
    DB seeded so each craft round-trips to its true home base:
      - C6062 departs/returns Borinquen for 3 days, plus one SJU outstation stop
      - N5854Z works the south grid, returns to Palo Seco (PREPA)
      - N767PD returns to the FURA base
      - N684JB and N111AB both rest at Isla Grande (co-location)
    """
    db = str(tmp_path / "hb.db")
    conn = sqlite3.connect(db)
    _schema(conn)

    # C6062 — three Borinquen round trips + one mid-day stop at SJU.
    for d in (15, 16, 17):
        _flight(conn, f"C6062_{d}a", "C6062", BORINQUEN, SJU,
                f"2024-03-{d}T08:00:00", f"2024-03-{d}T10:00:00")
        _flight(conn, f"C6062_{d}b", "C6062", SJU, BORINQUEN,
                f"2024-03-{d}T16:00:00", f"2024-03-{d}T18:00:00")

    # N5854Z — Palo Seco round trips.
    for d in (15, 16):
        _flight(conn, f"N5854Z_{d}a", "N5854Z", PALO_SECO, SJU,
                f"2024-03-{d}T07:00:00", f"2024-03-{d}T08:30:00")
        _flight(conn, f"N5854Z_{d}b", "N5854Z", SJU, PALO_SECO,
                f"2024-03-{d}T15:00:00", f"2024-03-{d}T16:30:00")

    # N767PD — FURA base round trips.
    for d in (15, 16):
        _flight(conn, f"N767PD_{d}a", "N767PD", FURA, SJU,
                f"2024-03-{d}T09:00:00", f"2024-03-{d}T09:45:00")
        _flight(conn, f"N767PD_{d}b", "N767PD", SJU, FURA,
                f"2024-03-{d}T17:00:00", f"2024-03-{d}T17:45:00")

    # N684JB and N111AB — both rest at Isla Grande.
    for cs in ("N684JB", "N111AB"):
        for d in (15, 16):
            _flight(conn, f"{cs}_{d}a", cs, ISLA_GRANDE, SJU,
                    f"2024-03-{d}T10:00:00", f"2024-03-{d}T11:00:00")
            _flight(conn, f"{cs}_{d}b", cs, SJU, ISLA_GRANDE,
                    f"2024-03-{d}T14:00:00", f"2024-03-{d}T15:00:00")

    conn.commit()
    conn.close()
    return db


# -- home-base resolution ----------------------------------------------------

def test_uscg_home_base_resolves_to_borinquen(home_base_db):
    spot = HomeBaseDeducer(home_base_db).home_base("C6062")
    assert spot.nearest_feature_id == "USCG_BORINQUEN"
    assert spot.nearest_operator == "USCG"


def test_overnight_weighting_beats_outstation(home_base_db):
    """SJU has more raw endpoints, but Borinquen wins on overnight anchoring."""
    spots = HomeBaseDeducer(home_base_db).cluster_resting_spots("C6062")
    assert spots[0].nearest_feature_id == "USCG_BORINQUEN"


def test_prepa_resolves_to_palo_seco(home_base_db):
    spot = HomeBaseDeducer(home_base_db).home_base("N5854Z")
    assert spot.nearest_feature_id == "PALO_SECO"
    assert spot.nearest_operator == "PREPA"


def test_fura_resolves_to_police(home_base_db):
    spot = HomeBaseDeducer(home_base_db).home_base("N767PD")
    assert spot.nearest_operator == "Puerto Rico Police"


# -- profile fusion ----------------------------------------------------------

def test_known_craft_corroborated_by_home_base(home_base_db):
    profile = HomeBaseDeducer(home_base_db).deduce_profile("C6062")
    assert profile.owner == "United States Coast Guard"
    evidence = profile.operational_patterns["home_base_evidence"]
    assert any("AGREES" in e for e in evidence)


def test_unknown_craft_deduced_from_distinctive_base(home_base_db):
    """An unregistered craft resting at Palo Seco is attributed to PREPA."""
    conn = sqlite3.connect(home_base_db)
    _flight(conn, "X1", "N999XX", PALO_SECO, SJU,
            "2024-03-15T07:00:00", "2024-03-15T08:00:00")
    _flight(conn, "X2", "N999XX", SJU, PALO_SECO,
            "2024-03-15T15:00:00", "2024-03-15T16:00:00")
    conn.commit()
    conn.close()

    profile = HomeBaseDeducer(home_base_db).deduce_profile("N999XX")
    assert profile.operator == "PREPA"
    assert profile.primary_mission == "Power Line Inspection"
    assert profile.data_source == "home_base"


# -- fleet co-location -------------------------------------------------------

def test_shared_base_groups_isla_grande_craft(home_base_db):
    groups = FleetColocationAnalyzer(home_base_db).shared_bases()
    assert set(groups.get("SIG", [])) >= {"N684JB", "N111AB"}


def test_uscg_is_isolated(home_base_db):
    groups = FleetColocationAnalyzer(home_base_db).shared_bases()
    assert groups.get("USCG_BORINQUEN") == ["C6062"]


def test_correlation_report_renders(home_base_db):
    report = FleetColocationAnalyzer(home_base_db).correlation_report()
    assert "Shared-space leads" in report
    assert "N684JB" in report and "N111AB" in report


# -- graceful no-DB fallback -------------------------------------------------

def test_no_db_falls_back_to_known_bases(tmp_path):
    deducer = HomeBaseDeducer(str(tmp_path / "missing.db"))
    spot = deducer.home_base("C6062")
    assert spot is not None
    assert spot.nearest_feature_id == "USCG_BORINQUEN"
