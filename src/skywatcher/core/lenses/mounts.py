"""Opt-in laboratory executable bindings over the canonical lens registry.

Only trusted application composition code may supply adapters. This module is
not a sandbox, authorization service, or production qualification mechanism.
No production dispatch is exposed until TheHub qualification is integrated.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from skywatcher.core.lenses.models import LensSpec
from skywatcher.core.lenses.registry import LensRegistry


def lens_fingerprint(lens: LensSpec) -> str:
    """Digest the normalized semantic contract, not the source file bytes."""
    payload = json.dumps(
        lens.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MountBinding:
    lens_id: str
    owner: str
    lens_version: str
    lens_digest: str
    adapter_version: str
    adapter: Callable[[Mapping[str, Any]], Mapping[str, Any]]


class MountBindings:
    """Discover executable adapters without duplicating lens definitions."""

    def __init__(
        self, registry: LensRegistry, bindings: Iterable[MountBinding] = ()
    ) -> None:
        self._registry = registry
        table: dict[str, MountBinding] = {}
        for binding in bindings:
            if binding.lens_id in table:
                raise ValueError("duplicate executable binding")
            if not callable(binding.adapter) or not binding.adapter_version:
                raise ValueError("invalid trusted adapter")
            self._verify(binding)
            table[binding.lens_id] = binding
        self._bindings = MappingProxyType(table)

    def _verify(self, binding: MountBinding) -> None:
        lens = self._registry.get(binding.lens_id)
        if lens.status == "deprecated":
            raise ValueError("deprecated lens cannot mount")
        if (lens.owner, lens.version, lens_fingerprint(lens)) != (
            binding.owner, binding.lens_version, binding.lens_digest
        ):
            raise ValueError("stale or mismatched lens binding")

    def discover(self) -> tuple[str, ...]:
        for binding in self._bindings.values():
            self._verify(binding)
        return tuple(sorted(self._bindings))

    def resolve(self, selected: Iterable[str]) -> tuple[MountBinding, ...]:
        ids = tuple(selected)
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate mount selection")
        resolved = tuple(self._bindings[lens_id] for lens_id in ids)
        for binding in resolved:
            self._verify(binding)
        return resolved

    def run_lab(
        self, lens_id: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Run one trusted adapter; raw result is never a certified finding."""
        binding, = self.resolve((lens_id,))
        result = binding.adapter(payload)
        if not isinstance(result, Mapping):
            raise TypeError("adapter must return a mapping")
        return {
            "lens_id": binding.lens_id,
            "lens_digest": binding.lens_digest,
            "adapter_version": binding.adapter_version,
            "qualification": "WITHHELD",
            "result": dict(result),
        }
