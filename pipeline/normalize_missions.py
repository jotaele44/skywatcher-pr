#!/usr/bin/env python3
"""RLSM mission, behavior, and blackout normalization helpers."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

from pipeline.normalize_locations import load_simple_yaml


def _norm(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.strip().lower().replace("ñ", "n")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _load_alias_map(path: Path, root_key: str) -> Dict[str, str]:
    if not path.exists():
        return {}
    data = load_simple_yaml(path)
    out: Dict[str, str] = {}
    root = data.get(root_key, {}) or {}
    if isinstance(root, dict):
        for canonical, body in root.items():
            out[_norm(canonical)] = canonical
            aliases = body.get("aliases", []) if isinstance(body, dict) else body
            for alias in aliases or []:
                out[_norm(alias)] = canonical
    return out


def normalize_mission(raw_text: str, config_dir: Path = Path("configs")) -> Dict[str, Any]:
    alias_map = _load_alias_map(config_dir / "mission_vocab.yaml", "mission_enums")
    key = _norm(raw_text)
    canonical = alias_map.get(key)
    return {
        "raw_text": raw_text,
        "mission_canonical": canonical or "UNKNOWN",
        "resolution_status": "resolved" if canonical else "unresolved_default_unknown",
        "visibility": "V1" if canonical else "V0",
        "raw_text_preserved": True,
    }


def normalize_blackout(raw_text: str, config_dir: Path = Path("configs")) -> Dict[str, Any]:
    alias_map = _load_alias_map(config_dir / "blackout_vocab.yaml", "blackout_classes")
    key = _norm(raw_text)
    canonical = alias_map.get(key)
    return {
        "raw_text": raw_text,
        "blackout_class": canonical or "UNKNOWN",
        "resolution_status": "resolved" if canonical else "unresolved_default_unknown",
        "do_not_assume_intentional": True,
        "visibility": "V1" if canonical else "V0",
        "raw_text_preserved": True,
    }


def normalize_behavior(raw_text: str, config_dir: Path = Path("configs")) -> Dict[str, Any]:
    if not (config_dir / "behavior_vocab.yaml").exists():
        return {"raw_text": raw_text, "behavior_tags": [], "resolution_status": "missing_vocab"}
    data = load_simple_yaml(config_dir / "behavior_vocab.yaml")
    families = data.get("behavior_families", {}) or {}
    key = _norm(raw_text)
    tags = []
    if isinstance(families, dict):
        for family, aliases in families.items():
            for alias in aliases or []:
                if _norm(alias) and _norm(alias) in key:
                    tags.append(family)
                    break
    return {
        "raw_text": raw_text,
        "behavior_tags": sorted(set(tags)),
        "resolution_status": "resolved" if tags else "unresolved",
        "visibility": "V1" if tags else "V0",
        "raw_text_preserved": True,
    }


def normalize_mission_record(event: Dict[str, Any], config_dir: Path = Path("configs")) -> Dict[str, Any]:
    result = dict(event)
    if event.get("mission_raw") or event.get("mission"):
        result["mission_normalized"] = normalize_mission(str(event.get("mission_raw") or event.get("mission")), config_dir=config_dir)
    if event.get("behavior_notes"):
        result["behavior_normalized"] = normalize_behavior(str(event["behavior_notes"]), config_dir=config_dir)
    if event.get("blackout_raw") or event.get("blackout"):
        result["blackout_normalized"] = normalize_blackout(str(event.get("blackout_raw") or event.get("blackout")), config_dir=config_dir)
    result["raw_text_preserved"] = True
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_text")
    parser.add_argument("--kind", choices=["mission", "behavior", "blackout"], default="mission")
    parser.add_argument("--config-dir", default="configs")
    args = parser.parse_args()
    func = {"mission": normalize_mission, "behavior": normalize_behavior, "blackout": normalize_blackout}[args.kind]
    print(json.dumps(func(args.raw_text, Path(args.config_dir)), indent=2, ensure_ascii=False))
