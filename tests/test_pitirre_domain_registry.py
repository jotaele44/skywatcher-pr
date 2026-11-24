import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from skywatcher.core.domain_registry import (
    AIR_SUBDOMAINS,
    DOMAIN_REGISTRY_VERSION,
    LAND_SUBDOMAINS,
    SPACE_SUBDOMAINS,
    TOP_LEVEL_DOMAINS,
    TRANSPORT_NETWORK_TYPES,
    WATER_SUBDOMAINS,
    DomainRegistryError,
    road_domain_path,
    validate_domain_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "configs" / "pitirre_domain_registry.json"
SCHEMA_PATH = REPO_ROOT / "schemas" / "pitirre_domain_registry.v1.schema.json"


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_serialized_registry_validates_against_its_schema():
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_registry())


def test_canonical_top_level_denominator_is_exact_and_ordered():
    assert TOP_LEVEL_DOMAINS == ("AIR", "LAND", "WATER", "SPACE")
    assert _registry()["top_level_domains"] == list(TOP_LEVEL_DOMAINS)


def test_registry_version_matches_core_contract():
    assert _registry()["registry_version"] == DOMAIN_REGISTRY_VERSION


def test_serialized_subdomains_match_core_contract():
    domains = _registry()["domains"]
    assert domains["AIR"]["subdomains"] == list(AIR_SUBDOMAINS)
    assert domains["LAND"]["subdomains"] == list(LAND_SUBDOMAINS)
    assert domains["WATER"]["subdomains"] == list(WATER_SUBDOMAINS)
    assert domains["SPACE"]["subdomains"] == list(SPACE_SUBDOMAINS)
    assert domains["LAND"]["transport_network_types"] == list(
        TRANSPORT_NETWORK_TYPES
    )


def test_road_is_land_transport_network_not_top_level_domain():
    registry = _registry()
    assert "ROAD" not in registry["top_level_domains"]
    assert "ROAD" in registry["domains"]["LAND"]["transport_network_types"]
    assert road_domain_path().canonical == "LAND.TRANSPORT.ROAD"


def test_road_top_level_fails_closed():
    with pytest.raises(DomainRegistryError):
        validate_domain_path("ROAD")


def test_network_type_requires_land_transport():
    with pytest.raises(DomainRegistryError):
        validate_domain_path("LAND", subdomain="FACILITY", network_type="ROAD")
    with pytest.raises(DomainRegistryError):
        validate_domain_path("WATER", subdomain="MARITIME", network_type="ROAD")


def test_exact_tokens_only_no_silent_normalization():
    with pytest.raises(DomainRegistryError):
        validate_domain_path("land", subdomain="transport", network_type="road")


def test_transport_registry_has_no_duplicate_network_types():
    assert len(TRANSPORT_NETWORK_TYPES) == len(set(TRANSPORT_NETWORK_TYPES))


@pytest.mark.parametrize(
    ("domain", "subdomain"),
    [
        ("AIR", "AVIATION"),
        ("LAND", "TERRAIN"),
        ("WATER", "MARITIME"),
        ("SPACE", "ORBITAL"),
    ],
)
def test_each_top_level_domain_has_a_valid_subdomain(domain, subdomain):
    assert validate_domain_path(domain, subdomain=subdomain).canonical == (
        f"{domain}.{subdomain}"
    )
