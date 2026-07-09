#!/usr/bin/env python3
"""RLSM aircraft/operator normalization helpers."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

from skywatcher.core.normalize_locations import load_simple_yaml

NA_VALUES = {
    "n/a",
    "n a",
    "na",
    "unknown",
    "blank",
    "private",
    "blocked",
    "suppressed",
    "no registration",
    "noregistration",
    "no callsign",
    "nocallsign",
    "",
}


def _norm(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.strip().lower().replace("ñ", "n")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_masked_identity(raw_tail: Any) -> bool:
    key = _norm(raw_tail)
    compact_key = key.replace(" ", "")
    return key in NA_VALUES or compact_key in NA_VALUES


class OperatorIndex:
    def __init__(self) -> None:
        self.aliases: Dict[str, Dict[str, Any]] = {}

    def add(self, alias: str, record: Dict[str, Any]) -> None:
        key = _norm(alias)
        if key and key not in self.aliases:
            self.aliases[key] = record

    def resolve_operator(self, raw_text: str) -> Dict[str, Any]:
        key = _norm(raw_text)
        record = self.aliases.get(key)
        if record:
            return {
                "raw_text": raw_text,
                "operator_id": record.get("operator_id"),
                "canonical_name": record.get("canonical_name"),
                "resolution_status": "resolved",
                "visibility": record.get("visibility", "V2"),
                "evidence_tier": record.get("evidence_tier", "T2"),
            }
        return {
            "raw_text": raw_text,
            "operator_id": None,
            "canonical_name": None,
            "resolution_status": "unresolved",
            "visibility": "V0",
            "evidence_tier": "T2",
        }


def build_operator_index(config_dir: Path = Path("configs")) -> OperatorIndex:
    index = OperatorIndex()
    path = config_dir / "operator_registry.yaml"
    if not path.exists():
        return index
    data = load_simple_yaml(path)
    for record in data.get("operator_buckets", []) or []:
        index.add(record.get("canonical_name", ""), record)
        for alias in record.get("aliases", []) or []:
            index.add(alias, record)
    return index


def normalize_aircraft_identity(raw_tail: Any, aircraft_type: Any = None) -> Dict[str, Any]:
    raw = "" if raw_tail is None else str(raw_tail).strip()
    key = _norm(raw)
    compact_key = key.replace(" ", "")
    if _is_masked_identity(raw):
        return {
            "raw_tail": raw_tail,
            "tail_canonical": None,
            "identity_status": "masked_or_unresolved",
            "merge_policy": "do_not_merge_without_cluster_evidence",
            "cluster_keys_required": ["time_proximity", "spatial_overlap", "behavior_similarity"],
            "aircraft_type_raw": aircraft_type,
            "visibility": "V0",
            "evidence_tier": "T2",
        }
    if re.fullmatch(r"n[0-9a-z]+", compact_key):
        return {
            "raw_tail": raw_tail,
            "tail_canonical": raw.upper().replace(" ", ""),
            "identity_status": "tail_candidate",
            "aircraft_type_raw": aircraft_type,
            "visibility": "V0",
            "evidence_tier": "T2",
        }
    return {
        "raw_tail": raw_tail,
        "tail_canonical": raw if raw else None,
        "identity_status": "unresolved_text",
        "aircraft_type_raw": aircraft_type,
        "visibility": "V0",
        "evidence_tier": "T2",
    }


def normalize_operator(raw_operator: str, config_dir: Path = Path("configs")) -> Dict[str, Any]:
    return build_operator_index(config_dir).resolve_operator(raw_operator)


def normalize_aircraft_record(event: Dict[str, Any], config_dir: Path = Path("configs")) -> Dict[str, Any]:
    result = dict(event)
    tail_raw = event.get("tail_raw") or event.get("tail") or event.get("registration") or event.get("callsign")
    result["aircraft_identity_normalized"] = normalize_aircraft_identity(tail_raw, event.get("aircraft_type"))
    op_raw = event.get("operator_raw") or event.get("operator")
    if op_raw:
        result["operator_normalized"] = normalize_operator(str(op_raw), config_dir=config_dir)
    result["raw_text_preserved"] = True
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_tail")
    parser.add_argument("--aircraft-type", default=None)
    args = parser.parse_args()
    print(json.dumps(normalize_aircraft_identity(args.raw_tail, args.aircraft_type), indent=2, ensure_ascii=False))
