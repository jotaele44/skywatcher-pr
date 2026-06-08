import json
import pathlib

from scripts.audit_fr24_repo_finalization import (
    REQUIRED_HARDENING_LAYERS,
    audit_manifest,
)


MANIFEST = pathlib.Path("data/reference/fr24_repo_finalization_operations_v1.json")


def test_fr24_repo_finalization_manifest_is_audit_clean():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert audit_manifest(manifest) == []


def test_fr24_repo_finalization_manifest_has_required_hardening_layers():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert REQUIRED_HARDENING_LAYERS.issubset(
        set(manifest["required_hardening_layers"])
    )


def test_fr24_repo_finalization_operations_are_contiguous_00_to_58():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert [op["order"] for op in manifest["operations"]] == list(range(59))
    assert manifest["operations"][0]["code"].startswith("00_")
    assert manifest["operations"][-1]["code"].startswith("58_")
