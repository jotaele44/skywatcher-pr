from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class ProviderProfileRegistry:
    def __init__(self):
        self._profiles: dict[str, dict[str, Any]] = {}

    def load_dir(self, directory: str | Path) -> int:
        count = 0
        for path in sorted(Path(directory).glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.register(data)
            count += 1
        return count

    def register(self, profile: Mapping[str, Any]) -> None:
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        if not profile_id:
            raise ValueError("provider profile requires profile_id or id")
        self._profiles[profile_id] = dict(profile)

    def get(self, profile_id: str) -> dict[str, Any]:
        return dict(self._profiles[profile_id])

    def compatible(self, profile_id: str, source: Mapping[str, Any]) -> bool:
        p = self._profiles[profile_id]
        # Provider / product scalars (schema field is ``product_or_sensor``;
        # legacy ``product`` is accepted for backward compatibility).
        for source_key, profile_keys in (
            ("provider", ("provider",)),
            ("product", ("product_or_sensor", "product")),
        ):
            expected = next(
                (p[k] for k in profile_keys if p.get(k) not in (None, "*", "")), None
            )
            if expected is not None and source.get(source_key) != expected:
                return False
        # Source type: the schema uses the ``source_types`` array; a singular
        # ``source_type`` string is accepted for backward compatibility.
        allowed = p.get("source_types")
        if allowed is None and p.get("source_type") not in (None, "*", ""):
            allowed = [p["source_type"]]
        if allowed and "*" not in allowed and source.get("source_type") not in allowed:
            return False
        return True
