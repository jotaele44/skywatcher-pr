"""Doctrine guard: the profile builder must not inject intent/mission inference.

Complements tests/test_fpim_quarantine.py — that guards the quarantined
FlightMissionAnalyzer; this guards the new craft-profile path.
"""

import sqlite3
from pathlib import Path

import pytest

from skywatcher.fpim import craft_profile
from skywatcher.fpim.craft_profile import CraftProfileBuilder


def test_builder_does_not_import_quarantined_inference():
    source = Path(craft_profile.__file__).read_text()
    assert "quarantined_mission_inference" not in source
    assert "AIRCRAFT_TYPE_MISSIONS" not in source
    assert "FlightMissionAnalyzer" not in source


def test_deduced_craft_never_asserts_mission(rlsm_db):
    conn = sqlite3.connect(rlsm_db)
    p = CraftProfileBuilder(db_path=Path(rlsm_db)).build_one(conn, "N999XY")
    conn.close()
    assert p.data_source != "known_db"
    assert p.mission_is_authoritative is False
    assert p.primary_mission is None


def test_known_craft_mission_is_operator_declared(rlsm_db):
    conn = sqlite3.connect(rlsm_db)
    p = CraftProfileBuilder(db_path=Path(rlsm_db)).build_one(conn, "N5854Z")
    conn.close()
    # Only known_db profiles may carry an authoritative mission.
    assert p.mission_is_authoritative is True
    assert p.data_source == "known_db"
