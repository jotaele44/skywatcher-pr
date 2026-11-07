"""Parity gates for PITIRRE AIR.AVIATION ADS-B + Core FR24 storage migration."""

from __future__ import annotations


def test_adsb_public_types_and_registry_are_canonical_objects():
    import adsb
    import adsb.providers as legacy_providers
    from adsb.providers.opensky import OpenSkyProvider as LegacyOpenSkyProvider
    from pitirre.domains.air.aviation import adsb as canonical_adsb
    from pitirre.domains.air.aviation.adsb import providers as canonical_providers
    from pitirre.domains.air.aviation.adsb.providers.opensky import (
        OpenSkyProvider as CanonicalOpenSkyProvider,
    )

    assert adsb.StateVector is canonical_adsb.StateVector
    assert legacy_providers.AdsbProvider is canonical_providers.AdsbProvider
    assert legacy_providers.ProviderError is canonical_providers.ProviderError
    assert legacy_providers.get_provider is canonical_providers.get_provider
    assert legacy_providers.available_providers is canonical_providers.available_providers
    assert LegacyOpenSkyProvider is CanonicalOpenSkyProvider


def test_adsb_module_aliases_resolve_to_canonical_modules():
    import adsb.config as legacy_config
    import adsb.models as legacy_models
    import adsb.providers.base as legacy_base
    import adsb.providers.opensky as legacy_opensky
    import adsb.sink as legacy_sink
    from pitirre.domains.air.aviation.adsb import config as canonical_config
    from pitirre.domains.air.aviation.adsb import models as canonical_models
    from pitirre.domains.air.aviation.adsb import sink as canonical_sink
    from pitirre.domains.air.aviation.adsb.providers import base as canonical_base
    from pitirre.domains.air.aviation.adsb.providers import opensky as canonical_opensky

    assert legacy_config is canonical_config
    assert legacy_models is canonical_models
    assert legacy_base is canonical_base
    assert legacy_opensky is canonical_opensky
    assert legacy_sink is canonical_sink


def test_fr24_database_modules_are_canonical_core_aliases():
    import skywatcher.fr24.database as legacy_db
    import skywatcher.fr24.database_migrations as legacy_migrations
    from pitirre.core.storage.fr24 import database as canonical_db
    from pitirre.core.storage.fr24 import database_migrations as canonical_migrations

    assert legacy_db is canonical_db
    assert legacy_migrations is canonical_migrations
    assert legacy_db.DatabaseError is canonical_db.DatabaseError
    assert legacy_migrations.initialize_database is canonical_migrations.initialize_database
    assert canonical_db.SCHEMA_SQL_PATH == canonical_db.REPO_ROOT / "schemas" / "database_schema.sql"
    assert canonical_db.REPO_ROOT.name == "skywatcher-pr"


def test_canonical_adsb_sink_and_legacy_db_share_one_storage_contract(tmp_path):
    from pitirre.core.storage.fr24 import database as canonical_db
    from pitirre.domains.air.aviation.adsb.models import StateVector
    from pitirre.domains.air.aviation.adsb.sink import persist_batch
    from skywatcher.fr24 import database as legacy_db

    state = StateVector(
        icao24="a1b2c3",
        callsign="N767PD",
        origin_country="United States",
        time_position=1700000000,
        last_contact=1700000005,
        longitude=-66.4,
        latitude=18.2,
        baro_altitude=1500.0,
        on_ground=False,
        velocity=120.5,
        true_track=270.0,
        vertical_rate=0.0,
        geo_altitude=1520.0,
        squawk="1200",
        position_source=0,
    )
    db_path = tmp_path / "pitirre.db"
    result = persist_batch([state], db_path=db_path, source_ref="parity-test")
    assert result["persisted"] is True
    assert result["n_written"] == 1

    assert legacy_db is canonical_db
    conn = legacy_db.connect(db_path, readonly=True)
    try:
        row = conn.execute(
            "SELECT icao24, callsign, longitude, latitude FROM adsb_state_vectors"
        ).fetchone()
        assert dict(row) == {
            "icao24": "a1b2c3",
            "callsign": "N767PD",
            "longitude": -66.4,
            "latitude": 18.2,
        }
    finally:
        conn.close()


def test_moved_legacy_files_are_wrapper_only():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    wrappers = (
        "adsb/config.py",
        "adsb/models.py",
        "adsb/providers/base.py",
        "adsb/providers/opensky.py",
        "adsb/sink.py",
        "src/skywatcher/fr24/database.py",
        "src/skywatcher/fr24/database_migrations.py",
    )
    for relative in wrappers:
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        definitions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        assert definitions == [], f"{relative} still contains implementation logic"


def test_adsb_facades_define_no_duplicate_implementation_logic():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for relative in ("adsb/__init__.py", "adsb/providers/__init__.py"):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        definitions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        assert definitions == [], f"{relative} contains duplicate definitions"
