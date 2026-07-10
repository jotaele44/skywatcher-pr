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
        for key in ("source_type", "provider", "product"):
            expected = p.get(key)
            if expected not in (None, "*", "") and source.get(key) != expected:
                return False
        return True
