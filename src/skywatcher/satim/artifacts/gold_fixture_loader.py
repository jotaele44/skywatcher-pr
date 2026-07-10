from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class GoldFixtureLoader:
    def load(self, path: str | Path) -> dict[str, Any]:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not data.get("case_id"):
            raise ValueError("gold fixture requires case_id")
        if data.get("split") not in {"train", "validation", "test", "challenge", None}:
            raise ValueError("invalid split")
        return data

    def assert_no_scene_leakage(self, fixtures: list[dict[str, Any]]) -> None:
        seen: dict[str, Any] = {}
        for f in fixtures:
            scene = f.get("source", {}).get("scene_id")
            split = f.get("split")
            if scene and scene in seen and seen[scene] != split:
                raise ValueError(f"scene leakage: {scene}")
            if scene:
                seen[scene] = split
