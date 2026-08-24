"""Load lens and objective-profile definitions from config directories.

Shaped after satim.artifacts.provider_registry.ProviderProfileRegistry — glob a
directory, key by id, expose lookups — because that is the registry pattern already
proven in this repo. The differences are deliberate:

  * YAML as well as JSON, via core.normalize_locations.load_simple_yaml, which is the
    repo-wide stdlib config loader. No PyYAML dependency is introduced; it is only a
    tools/satim_engine dep today and core must stay stdlib-first.
  * Definitions are parsed into frozen dataclasses at load time rather than kept as
    raw dicts, so a malformed lens fails when the registry loads instead of halfway
    through a run.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from skywatcher.core.lenses.models import LensSpec, ObjectiveProfile
from skywatcher.core.normalize_locations import load_simple_yaml

# Repo-root-relative defaults, resolved from this file so callers need not guess.
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_LENS_DIR = _REPO_ROOT / "configs" / "analysis" / "lenses"
DEFAULT_OBJECTIVE_DIR = _REPO_ROOT / "configs" / "analysis" / "objectives"

_SUFFIXES = (".yaml", ".yml", ".json")


def _load_mapping(path: Path) -> dict[str, Any]:
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = load_simple_yaml(path)
    if not isinstance(data, Mapping):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return dict(data)


def _definition_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob("*") if p.suffix in _SUFFIXES)


class LensRegistry:
    """Registry of analysis lenses, keyed by lens_id."""

    def __init__(self) -> None:
        self._lenses: dict[str, LensSpec] = {}

    def load_dir(self, directory: str | Path | None = None) -> int:
        directory = Path(directory) if directory is not None else DEFAULT_LENS_DIR
        if not directory.is_dir():
            raise FileNotFoundError(f"lens directory not found: {directory}")
        count = 0
        for path in _definition_files(directory):
            try:
                self.register(LensSpec.from_mapping(_load_mapping(path)))
            except ValueError as exc:
                # Name the offending file: a bare "unknown owner ''" from a 20-file
                # directory is unactionable.
                raise ValueError(f"{path}: {exc}") from exc
            count += 1
        return count

    def register(self, lens: LensSpec) -> None:
        if lens.lens_id in self._lenses:
            raise ValueError(f"duplicate lens_id: {lens.lens_id}")
        self._lenses[lens.lens_id] = lens

    def get(self, lens_id: str) -> LensSpec:
        return self._lenses[lens_id]

    def lens_ids(self) -> list[str]:
        return sorted(self._lenses)

    def all(self) -> list[LensSpec]:
        return [self._lenses[k] for k in sorted(self._lenses)]

    def for_stage(self, stage: str) -> list[LensSpec]:
        return [lens for lens in self.all() if lens.stage == stage]

    def for_owner(self, owner: str) -> list[LensSpec]:
        return [lens for lens in self.all() if lens.owner == owner]

    def threshold_ids(self) -> list[str]:
        ids: set[str] = set()
        for lens in self._lenses.values():
            ids.update(lens.threshold_ids)
            ids.update(
                p.threshold_id for p in lens.all_parameters() if p.threshold_id
            )
        return sorted(ids)

    def to_dict(self) -> dict[str, Any]:
        return {"lenses": [lens.to_dict() for lens in self.all()]}

    def __len__(self) -> int:
        return len(self._lenses)

    def __contains__(self, lens_id: object) -> bool:
        return lens_id in self._lenses


class ObjectiveProfileRegistry:
    """Registry of objective profiles, keyed by profile_id."""

    def __init__(self) -> None:
        self._profiles: dict[str, ObjectiveProfile] = {}

    def load_dir(self, directory: str | Path | None = None) -> int:
        directory = Path(directory) if directory is not None else DEFAULT_OBJECTIVE_DIR
        if not directory.is_dir():
            raise FileNotFoundError(f"objective directory not found: {directory}")
        count = 0
        for path in _definition_files(directory):
            try:
                self.register(ObjectiveProfile.from_mapping(_load_mapping(path)))
            except ValueError as exc:
                raise ValueError(f"{path}: {exc}") from exc
            count += 1
        return count

    def register(self, profile: ObjectiveProfile) -> None:
        if profile.profile_id in self._profiles:
            raise ValueError(f"duplicate profile_id: {profile.profile_id}")
        self._profiles[profile.profile_id] = profile

    def get(self, profile_id: str) -> ObjectiveProfile:
        return self._profiles[profile_id]

    def profile_ids(self) -> list[str]:
        return sorted(self._profiles)

    def all(self) -> list[ObjectiveProfile]:
        return [self._profiles[k] for k in sorted(self._profiles)]

    def to_dict(self) -> dict[str, Any]:
        return {"objectives": [p.to_dict() for p in self.all()]}

    def __len__(self) -> int:
        return len(self._profiles)

    def __contains__(self, profile_id: object) -> bool:
        return profile_id in self._profiles


def resolve_profile_lenses(
    profile: ObjectiveProfile, registry: LensRegistry
) -> tuple[list[LensSpec], list[str]]:
    """Split a profile's lens references into resolved specs and dangling ids.

    Returned rather than raised: a profile naming a lens that no longer exists is a
    coverage failure to report, not an import-time crash that hides the rest of the run.
    """
    resolved: list[LensSpec] = []
    dangling: list[str] = []
    for lens_id in tuple(profile.required_lenses) + tuple(profile.optional_lenses):
        if lens_id in registry:
            resolved.append(registry.get(lens_id))
        else:
            dangling.append(lens_id)
    return resolved, dangling


def load_default_registries() -> tuple[LensRegistry, ObjectiveProfileRegistry]:
    """Load both registries from the committed configs/analysis tree."""
    lenses = LensRegistry()
    lenses.load_dir()
    objectives = ObjectiveProfileRegistry()
    objectives.load_dir()
    return lenses, objectives


def unknown_lens_references(
    profiles: Iterable[ObjectiveProfile], registry: LensRegistry
) -> dict[str, list[str]]:
    """Every profile's dangling lens references, keyed by profile_id."""
    out: dict[str, list[str]] = {}
    for profile in profiles:
        _, dangling = resolve_profile_lenses(profile, registry)
        if dangling:
            out[profile.profile_id] = dangling
    return out
