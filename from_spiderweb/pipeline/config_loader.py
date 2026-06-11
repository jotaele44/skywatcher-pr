"""Central YAML config loader with light validation (T10-85).

The ``configs/*.yaml`` registries were each loaded ad-hoc. This module gives one
fail-closed entry point: it parses a YAML file, confirms it is a mapping, and
optionally checks that required top-level keys are present. No heavy schema
dependency — just enough validation to turn a malformed config into a clear
error instead of a downstream ``KeyError``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Optional


class ConfigError(ValueError):
    """Raised when a config file is missing, unparseable, or fails validation."""


def load_yaml_config(
    path: str | Path,
    *,
    required_keys: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Load and validate a YAML config file.

    Args:
        path: path to the ``.yaml`` file.
        required_keys: top-level keys that must be present (optional).

    Returns:
        The parsed mapping.

    Raises:
        ConfigError: file missing, not valid YAML, not a mapping, or missing a
            required key.
    """
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config not found: {p}")

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - PyYAML ships in the airspace extra
        raise ConfigError("PyYAML is required to load configs") from exc

    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {p}: {exc}") from exc

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"config {p} must be a mapping, got {type(data).__name__}")

    if required_keys:
        missing = [k for k in required_keys if k not in data]
        if missing:
            raise ConfigError(f"config {p} missing required keys: {missing}")

    return data
