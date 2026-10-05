"""Parity gates for the first physical PITIRRE Core/AIR migration slice."""


def test_domain_registry_aliases_are_the_canonical_objects():
    from pitirre.compat.skywatcher.core import domain_registry as compat
    from pitirre.core.domains import registry as canonical
    from skywatcher.core import domain_registry as legacy

    assert canonical.TOP_LEVEL_DOMAINS == ("AIR", "LAND", "WATER", "SPACE")
    assert legacy.validate_domain_path is canonical.validate_domain_path
    assert compat.validate_domain_path is canonical.validate_domain_path
    assert legacy.DomainPath is canonical.DomainPath
    assert compat.DomainRegistryError is canonical.DomainRegistryError
    assert canonical.road_domain_path().canonical == "LAND.TRANSPORT.ROAD"


def test_observation_contract_aliases_are_the_canonical_objects():
    from pitirre.compat.skywatcher.core import pitirre_observation as compat
    from pitirre.core.contracts import observation as canonical
    from skywatcher.core import pitirre_observation as legacy

    assert legacy.PitirreObservation is canonical.PitirreObservation
    assert compat.PitirreObservation is canonical.PitirreObservation
    assert legacy.adapt_airspace_observation is canonical.adapt_airspace_observation
    assert compat.adapt_maritime_baseline is canonical.adapt_maritime_baseline


def test_air_normalizer_aliases_share_one_canonical_function_and_contract():
    from pitirre.compat.skywatcher.normalizers.air_event_normalizer import (
        normalize_air_event as compat_normalize,
    )
    from pitirre.core.contracts.air_event import validate_air_event_contract
    from pitirre.core.normalization.air_event import normalize_air_event as canonical_normalize
    from pitirre.domains.air.events import normalize_air_event as air_facade_normalize
    from skywatcher.normalizers.air_event_normalizer import normalize_air_event as legacy_normalize

    assert legacy_normalize is canonical_normalize
    assert compat_normalize is canonical_normalize
    assert air_facade_normalize is canonical_normalize

    unknown = canonical_normalize(
        {
            "registration": "N407PR",
            "timestamp": "2026-10-04T12:00:00Z",
            "lat": "",
            "lon": None,
        }
    )
    assert unknown["lat"] is None
    assert unknown["lon"] is None
    assert unknown["geometry_status"] == "UNRESOLVED"
    validate_air_event_contract(unknown)

    zero = canonical_normalize(
        {
            "registration": "N407PR",
            "timestamp": "2026-10-04T12:00:00Z",
            "lat": 0,
            "lon": 0,
        }
    )
    assert zero["lat"] == 0.0
    assert zero["lon"] == 0.0
    assert zero["geometry_status"] == "LOCATED"
    validate_air_event_contract(zero)


def test_air_domain_registry_has_exact_declared_subdomains():
    from pitirre.domains.air import AIR_DOMAIN, AIR_SUBDOMAIN_PATHS
    from pitirre.domains.air.aerostat import DOMAIN_PATH as aerostat
    from pitirre.domains.air.airspace import DOMAIN_PATH as airspace
    from pitirre.domains.air.atmospheric_sensor import DOMAIN_PATH as atmospheric_sensor
    from pitirre.domains.air.aviation import DOMAIN_PATH as aviation

    assert AIR_DOMAIN.canonical == "AIR"
    assert tuple(path.canonical for path in AIR_SUBDOMAIN_PATHS) == (
        "AIR.AVIATION",
        "AIR.AIRSPACE",
        "AIR.AEROSTAT",
        "AIR.ATMOSPHERIC_SENSOR",
    )
    assert aviation.canonical == "AIR.AVIATION"
    assert airspace.canonical == "AIR.AIRSPACE"
    assert aerostat.canonical == "AIR.AEROSTAT"
    assert atmospheric_sensor.canonical == "AIR.ATMOSPHERIC_SENSOR"


def test_historical_implementation_paths_are_wrapper_only():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    paths = (
        "src/skywatcher/core/domain_registry.py",
        "src/skywatcher/core/pitirre_observation.py",
        "src/skywatcher/normalizers/air_event_normalizer.py",
    )
    for relative in paths:
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        definitions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        assert definitions == [], f"{relative} contains implementation definitions"


def test_canonical_core_does_not_import_analytical_packages():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    forbidden = ("skywatcher.satim", "skywatcher.fpim", "skywatcher.corrim", "skywatcher.legacy")
    violations = []
    for path in (root / "src" / "pitirre" / "core").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(forbidden):
                        violations.append((path, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                name = node.module
                if name.startswith(forbidden):
                    violations.append((path, name))
    assert violations == []
