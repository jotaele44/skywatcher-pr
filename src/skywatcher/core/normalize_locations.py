#!/usr/bin/env python3
"""RLSM location normalization helpers.

Pure-stdlib registry loader for airport/place/LZ/hangar/POI alias resolution.
The module preserves raw text and returns explicit unresolved records instead of guessing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

VALID_VISIBILITY = {"V0", "V1", "V2", "V3", "V4"}


def _norm(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.strip().lower()
    text = re.sub(r"[\u0300-\u036f]", "", text)
    text = text.replace("ñ", "n")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _record_identity(record: Dict[str, Any]) -> str:
    for field in ("airport_id", "canonical_id", "lz_id", "hangar_id", "corridor_id", "project_location_id"):
        if record.get(field):
            return str(record[field])
    return str(record.get("canonical_name", ""))


def _parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if raw in {"null", "None", ""}:
        return None
    if raw in {"true", "false"}:
        return raw == "true"
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def _parse_inline_list(raw: str) -> List[str]:
    raw = raw.strip()
    if not (raw.startswith("[") and raw.endswith("]")):
        return [raw]
    inner = raw[1:-1].strip()
    if not inner:
        return []
    return [part.strip().strip('"').strip("'") for part in inner.split(",")]


def _strip_comment(line: str) -> str:
    """Remove simple full/inline comments outside the project YAML subset values."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    return line.split("#", 1)[0].rstrip()


def _prepared_lines(path: Path) -> List[Tuple[int, str]]:
    out: List[Tuple[int, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        out.append((indent, line.strip()))
    return out


def load_simple_yaml(path: Path) -> Dict[str, Any]:
    """Load the small YAML subset used by configs without external dependencies."""
    if not path.exists():
        raise FileNotFoundError(path)

    lines = _prepared_lines(path)
    if not lines:
        return {}

    def parse_value(value: str) -> Any:
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            return _parse_inline_list(value)
        return _parse_scalar(value)

    def parse_block(index: int, indent: int) -> Tuple[Any, int]:
        if index >= len(lines):
            return {}, index

        is_list = lines[index][0] == indent and lines[index][1].startswith("- ")
        if is_list:
            result: List[Any] = []
            while index < len(lines):
                current_indent, text = lines[index]
                if current_indent < indent:
                    break
                if current_indent > indent:
                    raise ValueError(f"Unexpected nested list indentation in {path}: {text}")
                if not text.startswith("- "):
                    break

                item_text = text[2:].strip()
                index += 1
                if item_text == "":
                    if index < len(lines) and lines[index][0] > current_indent:
                        child, index = parse_block(index, lines[index][0])
                        result.append(child)
                    else:
                        result.append(None)
                    continue

                if ":" in item_text:
                    key, value = item_text.split(":", 1)
                    item: Dict[str, Any] = {}
                    key = key.strip()
                    value = value.strip()
                    if value:
                        item[key] = parse_value(value)
                    elif index < len(lines) and lines[index][0] > current_indent:
                        child, index = parse_block(index, lines[index][0])
                        item[key] = child
                    else:
                        item[key] = None

                    while index < len(lines) and lines[index][0] > current_indent:
                        child_indent, child_text = lines[index]
                        if child_indent <= current_indent:
                            break
                        if child_text.startswith("- "):
                            break
                        if ":" not in child_text:
                            raise ValueError(f"Malformed mapping item in {path}: {child_text}")
                        child_key, child_value = child_text.split(":", 1)
                        child_key = child_key.strip()
                        child_value = child_value.strip()
                        index += 1
                        if child_value:
                            item[child_key] = parse_value(child_value)
                        elif index < len(lines) and lines[index][0] > child_indent:
                            grandchild, index = parse_block(index, lines[index][0])
                            item[child_key] = grandchild
                        else:
                            item[child_key] = None
                    result.append(item)
                else:
                    result.append(parse_value(item_text))
            return result, index

        result_dict: Dict[str, Any] = {}
        while index < len(lines):
            current_indent, text = lines[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ValueError(f"Unexpected mapping indentation in {path}: {text}")
            if text.startswith("- "):
                break
            if ":" not in text:
                raise ValueError(f"Malformed mapping line in {path}: {text}")
            key, value = text.split(":", 1)
            key = key.strip()
            value = value.strip()
            index += 1
            if value:
                result_dict[key] = parse_value(value)
            elif index < len(lines) and lines[index][0] > current_indent:
                child, index = parse_block(index, lines[index][0])
                result_dict[key] = child
            else:
                result_dict[key] = None
        return result_dict, index

    parsed, next_index = parse_block(0, lines[0][0])
    if next_index != len(lines):
        raise ValueError(f"Unparsed YAML content in {path} at line index {next_index}")
    if not isinstance(parsed, dict):
        raise ValueError(f"Top-level YAML content must be a mapping: {path}")
    return parsed


class AliasIndex:
    def __init__(self) -> None:
        self.alias_to_record: Dict[str, Dict[str, Any]] = {}
        self.collisions: Dict[str, List[Dict[str, Any]]] = {}

    def add(self, alias: str, record: Dict[str, Any]) -> None:
        key = _norm(alias)
        if not key:
            return
        if key in self.alias_to_record:
            existing = self.alias_to_record[key]
            same_identity = _record_identity(existing) == _record_identity(record)
            same_name = _norm(existing.get("canonical_name")) == _norm(record.get("canonical_name"))
            if same_identity or same_name:
                return
            self.collisions.setdefault(key, [existing]).append(record)
            return
        self.alias_to_record[key] = record

    def resolve(self, raw_text: str, namespace: str = "location") -> Dict[str, Any]:
        key = _norm(raw_text)
        if key in self.collisions:
            return {
                "raw_text": raw_text,
                "normalized_id": None,
                "canonical_name": None,
                "namespace": namespace,
                "resolution_status": "collision_review_required",
                "visibility": "V2",
                "candidate_count": len(self.collisions[key]),
            }
        record = self.alias_to_record.get(key)
        if record:
            return {
                "raw_text": raw_text,
                "normalized_id": record.get("canonical_id") or record.get("airport_id") or record.get("lz_id") or record.get("hangar_id") or record.get("corridor_id"),
                "canonical_name": record.get("canonical_name"),
                "namespace": namespace,
                "resolution_status": "resolved",
                "visibility": record.get("visibility", "V3"),
                "record": record,
            }
        return {
            "raw_text": raw_text,
            "normalized_id": None,
            "canonical_name": None,
            "namespace": namespace,
            "resolution_status": "unresolved",
            "visibility": "V0",
        }


def build_location_index(config_dir: Path = Path("configs")) -> AliasIndex:
    index = AliasIndex()
    for filename, collection_key in [
        ("airport_registry.yaml", "airports"),
        ("place_aliases.yaml", "places"),
        ("lz_registry.yaml", "known_lz_candidates"),
        ("hangar_registry.yaml", "known_hangar_candidates"),
        # Renamed from corridor_registry.yaml at rebase time (2026-06-02): main's
        # `configs/corridor_registry.yaml` is an observed-corridor catalog with a
        # different schema (canonical_id / flights_logged / top_pois). The ontology
        # layer's canonical-name + aliases live in `corridor_aliases.yaml` —
        # parallel to `operator_aliases.yaml`.
        ("corridor_aliases.yaml", "corridors"),
    ]:
        path = config_dir / filename
        if not path.exists():
            continue
        data = load_simple_yaml(path)
        for record in data.get(collection_key, []) or []:
            for field in ("canonical_name", "iata", "icao"):
                if record.get(field):
                    index.add(str(record[field]), record)
            for alias in record.get("aliases", []) or []:
                index.add(alias, record)
    return index


def normalize_location(raw_text: str, config_dir: Path = Path("configs"), namespace: str = "location") -> Dict[str, Any]:
    return build_location_index(config_dir).resolve(raw_text, namespace=namespace)


# ── Shared PR natural-features gazetteer (terrain + coastal slice) ─────────────
# The federation's canonical natural-features gazetteer is owned by spiderweb-pr;
# skywatcher/ovnis consume the terrain+coastal slice (mountains, peaks, ridges,
# valleys, capes, bays, beaches, islands …). It is loaded from a JSON registry —
# not the restricted-YAML subset — because the 991 free-text GNIS names carry
# commas/accents that the minimal YAML parser cannot represent. It is kept in a
# SEPARATE index from build_location_index() so a gazetteer name never collides
# with an airport/place alias the ontology gate depends on (e.g. the island
# "Isla Verde" vs the SJU alias "Isla Verde").
NATURAL_FEATURES_REGISTRY = "natural_features_registry.json"


def build_natural_feature_index(config_dir: Path = Path("configs")) -> AliasIndex:
    index = AliasIndex()
    path = config_dir / NATURAL_FEATURES_REGISTRY
    if not path.exists():
        return index
    data = json.loads(path.read_text(encoding="utf-8"))
    # Unlike the airport/place index, distinct features legitimately share a name
    # (e.g. "Arrecife Algarrobo" in Mayagüez and Guayama). AliasIndex.add() would
    # dedup same-name/different-id as one record and silently keep the first; here
    # we group by normalized key and flag any key mapping to >1 canonical_id as a
    # collision so resolve() returns collision_review_required instead of guessing.
    key_to_records: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for record in data.get("natural_features", []) or []:
        cid = record.get("canonical_id")
        for alias in [record.get("canonical_name"), *(record.get("aliases", []) or [])]:
            key = _norm(alias)
            if key:
                key_to_records.setdefault(key, {})[cid] = record
    for key, by_id in key_to_records.items():
        if len(by_id) == 1:
            index.alias_to_record[key] = next(iter(by_id.values()))
        else:
            index.collisions[key] = list(by_id.values())
    return index


def normalize_natural_feature(
    raw_text: str,
    config_dir: Path = Path("configs"),
    namespace: str = "natural_feature",
) -> Dict[str, Any]:
    """Resolve a raw place string to a canonical PR natural feature. Returns the
    same shape as normalize_location(); normalized_id is the feature canonical_id."""
    return build_natural_feature_index(config_dir).resolve(raw_text, namespace=namespace)


def normalize_flight_locations(event: Dict[str, Any], config_dir: Path = Path("configs")) -> Dict[str, Any]:
    result = dict(event)
    for raw_field, normalized_field in [
        ("origin_raw", "origin_normalized"),
        ("destination_raw", "destination_normalized"),
        ("origin_airport", "origin_airport_normalized"),
        ("destination_airport", "destination_airport_normalized"),
    ]:
        if raw_field in event and event.get(raw_field):
            result[normalized_field] = normalize_location(str(event[raw_field]), config_dir=config_dir)
    result["raw_text_preserved"] = True
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_text")
    parser.add_argument("--config-dir", default="configs")
    args = parser.parse_args()
    print(json.dumps(normalize_location(args.raw_text, Path(args.config_dir)), indent=2, ensure_ascii=False))
