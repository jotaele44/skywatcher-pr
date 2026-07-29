from pathlib import Path

from skywatcher import cli


def test_validate_fails_when_schema_assets_absent(tmp_path):
    assert cli._validate(tmp_path) == 1


def test_validate_checks_nonzero_repository_schemas():
    root = Path(__file__).resolve().parents[1]
    assert cli._validate(root) == 0
