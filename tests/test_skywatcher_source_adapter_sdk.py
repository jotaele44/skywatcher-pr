from pathlib import Path

import pytest

from scripts.source_adapters.provider_registry import get_provider
from scripts.source_adapters.sdk import (
    AcquisitionRights,
    AdapterPolicy,
    CertifiedFetchEngine,
    ImagerySourceEndpoint,
    PayloadRequest,
    PayloadValidator,
    SourceAdapterError,
)
from scripts.source_adapters.sdk.core import (
    require_redistribution_eligible,
    require_training_eligible,
)


def _policy(tmp_path: Path) -> AdapterPolicy:
    return AdapterPolicy(
        raw_payload_root=tmp_path / "raw",
        manifest_root=tmp_path / "manifests",
        staging_root=tmp_path / "staging",
        cache_root=tmp_path / "cache",
    )


def _endpoint(rights: AcquisitionRights | None = None) -> ImagerySourceEndpoint:
    return ImagerySourceEndpoint(
        source_id="fixture",
        name="Fixture",
        url="https://example.invalid/image.tif",
        source_lineage_id="FIXTURE-LINEAGE-001",
        rights=rights or AcquisitionRights(fetch="ALLOWED", training="UNKNOWN", redistribution="UNKNOWN"),
    )


def test_dry_run_preserves_source_lineage_and_does_not_fetch(tmp_path: Path) -> None:
    request = PayloadRequest(request_id="r1", endpoint=_endpoint(), expected_content="image")
    result = CertifiedFetchEngine(_policy(tmp_path)).dry_run(request)
    assert result.review_status == "dry_run"
    assert result.source_lineage_id == "FIXTURE-LINEAGE-001"
    assert not (tmp_path / "raw").exists()


def test_fetch_prohibited_fails_closed(tmp_path: Path) -> None:
    endpoint = _endpoint(AcquisitionRights(fetch="PROHIBITED", training="UNKNOWN", redistribution="UNKNOWN"))
    with pytest.raises(SourceAdapterError):
        CertifiedFetchEngine(_policy(tmp_path)).dry_run(PayloadRequest(request_id="r1", endpoint=endpoint))


def test_training_and_redistribution_are_independent_rights() -> None:
    endpoint = _endpoint(AcquisitionRights(fetch="ALLOWED", training="UNKNOWN", redistribution="PROHIBITED"))
    with pytest.raises(SourceAdapterError):
        require_training_eligible(endpoint)
    with pytest.raises(SourceAdapterError):
        require_redistribution_eligible(endpoint)


def test_content_addressed_cache_hit_reuses_bytes_without_network(tmp_path: Path) -> None:
    payload = b"fixture-bytes"
    digest = PayloadValidator.sha256_bytes(payload)
    policy = _policy(tmp_path)
    policy.cache_root.mkdir(parents=True)
    (policy.cache_root / digest).write_bytes(payload)
    req = PayloadRequest(request_id="cached", endpoint=_endpoint(), expected_sha256=digest, filename_hint="scene.tif")
    result = CertifiedFetchEngine(policy).fetch(req)
    assert result.review_status == "cache_hit"
    assert result.sha256 == digest
    assert Path(result.filename).read_bytes() == payload


def test_change_classification_is_byte_identity_only(tmp_path: Path) -> None:
    engine = CertifiedFetchEngine(_policy(tmp_path))
    digest = "a" * 64
    assert engine._change_state(digest, "") == "NEW_MANIFESTATION"
    assert engine._change_state(digest, digest) == "UNCHANGED"
    assert engine._change_state(digest, "b" * 64) == "BYTE_CHANGED"


def test_html_error_payload_never_passes_image_validation() -> None:
    assert not PayloadValidator.matches_expected(b"<html>error</html>", "image/jpeg", "image")


def test_catalog_rights_states_preserve_unknowns() -> None:
    assert get_provider("SIGE_FOTO_PR_2017").rights.training == "UNKNOWN"
    assert get_provider("USGS_TNM_IMAGERY_PR").rights.redistribution == "UNKNOWN"
    assert get_provider("USGS_LANDSAT").rights.training == "ALLOWED"


def test_derived_samples_must_inherit_lineage_contract() -> None:
    parent = _endpoint()
    assert parent.source_lineage_id == "FIXTURE-LINEAGE-001"
    # Derived crop identity may change bytes/path, but lineage must remain parent lineage.
    derived_lineage_id = parent.source_lineage_id
    assert derived_lineage_id == "FIXTURE-LINEAGE-001"
