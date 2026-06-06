from pathlib import Path

from scripts.validate_airspace_export import validate_package


PACKAGE_DIR = Path("exports/examples/synthetic_airspace_package")


def test_synthetic_package_passes_in_test_mode():
    assert validate_package(PACKAGE_DIR, "test") == []


def test_synthetic_package_fails_in_production_mode():
    errors = validate_package(PACKAGE_DIR, "production")
    assert errors
    assert any("synthetic rows are not allowed" in error for error in errors)
