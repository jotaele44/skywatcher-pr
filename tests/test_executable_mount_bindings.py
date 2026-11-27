"""Isolated tests of opt-in executable binding identity and dispatch."""
from dataclasses import replace

import pytest

from skywatcher.core.lenses.models import LensSpec
from skywatcher.core.lenses.mounts import (
    MountBinding,
    MountBindings,
    lens_fingerprint,
)
from skywatcher.core.lenses.registry import LensRegistry


@pytest.fixture
def setup_binding():
    registry = LensRegistry()
    lens = LensSpec(
        lens_id="satim.test", name="Test", owner="SATIM",
        stage="satellite_image_processing", objective="Synthetic test only",
    )
    registry.register(lens)
    binding = MountBinding(
        lens.lens_id, lens.owner, lens.version, lens_fingerprint(lens),
        "test-v1", lambda payload: {"value": payload["value"]},
    )
    return registry, binding


def test_empty_core(setup_binding):
    registry, _ = setup_binding
    mounts = MountBindings(registry)
    assert mounts.discover() == ()
    assert mounts.resolve(()) == ()
    with pytest.raises(KeyError):
        mounts.resolve(("satim.test",))


def test_lab_dispatch_never_certifies(setup_binding):
    registry, binding = setup_binding
    mounts = MountBindings(registry, (binding,))
    assert mounts.discover() == ("satim.test",)
    result = mounts.run_lab("satim.test", {"value": 7})
    assert result["result"] == {"value": 7}
    assert result["qualification"] == "WITHHELD"


@pytest.mark.parametrize("field,value", [
    ("owner", "FPIM"), ("lens_version", "wrong"),
    ("lens_digest", "0" * 64), ("adapter_version", ""),
    ("adapter", "untrusted.import"),
])
def test_reject_invalid_bindings(setup_binding, field, value):
    registry, binding = setup_binding
    with pytest.raises(ValueError):
        MountBindings(registry, (replace(binding, **{field: value}),))


def test_reject_duplicates_and_unbound(setup_binding):
    registry, binding = setup_binding
    with pytest.raises(ValueError):
        MountBindings(registry, (binding, binding))
    mounts = MountBindings(registry, (binding,))
    with pytest.raises(ValueError):
        mounts.resolve(("satim.test", "satim.test"))
    with pytest.raises(KeyError):
        mounts.resolve(("satim.unknown",))


def test_reject_deprecated(setup_binding):
    registry, binding = setup_binding
    lens = replace(registry.get(binding.lens_id), status="deprecated")
    other = LensRegistry()
    other.register(lens)
    with pytest.raises(ValueError, match="deprecated"):
        MountBindings(other, (replace(binding, lens_digest=lens_fingerprint(lens)),))


def test_adapter_failure_propagates(setup_binding):
    registry, binding = setup_binding

    def fail(payload):
        raise RuntimeError("synthetic failure")

    mounts = MountBindings(registry, (replace(binding, adapter=fail),))
    with pytest.raises(RuntimeError, match="synthetic failure"):
        mounts.run_lab(binding.lens_id, {})


def test_invalid_result_rejected(setup_binding):
    registry, binding = setup_binding
    mounts = MountBindings(registry, (replace(binding, adapter=lambda payload: None),))
    with pytest.raises(TypeError):
        mounts.run_lab(binding.lens_id, {})
