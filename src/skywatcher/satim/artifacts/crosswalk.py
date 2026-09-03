"""Loader for the artifact crosswalk — one table replacing six scattered ones.

``compound_artifacts.PRIORITY``, the taxonomy's per-class ``priority`` integer,
``restriction_gate.CLASS_MINIMUM``, the taxonomy's ``restriction`` prose, and the four
``L5_*`` dicts in ``pipeline_chain`` all encoded overlapping facts about the same 12
classes, with nothing keeping them in agreement. They now read from
``artifact_crosswalk_v1.json``.

Loaded once at import: the file is small, every consumer needs it, and the modules that
read it expose module-level constants that must exist at import time.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CROSSWALK_PATH = Path(__file__).with_name("artifact_crosswalk_v1.json")

# Vocabularies the crosswalk maps between. Named here so a typo in the data file is a
# load-time failure rather than a silently empty lookup.
VOCABULARIES = (
    "observation_class",
    "tile_artifact",
    "tile_artifact_ledger",
    "artifact_signal",
)


@lru_cache(maxsize=1)
def load_crosswalk() -> dict[str, Any]:
    data = json.loads(CROSSWALK_PATH.read_text(encoding="utf-8"))
    classes = data["classes"]

    ranks = [entry["arbitration_rank"] for entry in classes.values()]
    if len(set(ranks)) != len(ranks):
        raise ValueError("artifact crosswalk: arbitration_rank must be unique")
    if sorted(ranks) != list(range(len(ranks))):
        raise ValueError("artifact crosswalk: arbitration_rank must be dense from 0")

    for class_id, entry in classes.items():
        unknown = set(entry.get("vocabulary", {})) - set(VOCABULARIES)
        if unknown:
            raise ValueError(f"{class_id}: unknown vocabulary key(s) {sorted(unknown)}")
        ambiguous = entry.get("vocabulary_ambiguous")
        if ambiguous:
            unknown = set(ambiguous) - set(VOCABULARIES) - {"reason"}
            if unknown:
                raise ValueError(
                    f"{class_id}: unknown vocabulary_ambiguous key(s) {sorted(unknown)}"
                )
            if not ambiguous.get("reason", "").strip():
                raise ValueError(
                    f"{class_id}: vocabulary_ambiguous must say why the term was "
                    "assigned elsewhere"
                )
    return data


def class_ids() -> tuple[str, ...]:
    """Class ids in arbitration order — first is the strongest claim."""
    classes = load_crosswalk()["classes"]
    return tuple(sorted(classes, key=lambda cid: classes[cid]["arbitration_rank"]))


def restriction_minimums() -> dict[str, str]:
    """Class id to mandatory restriction floor, omitting the NONE defaults."""
    return {
        class_id: entry["restriction_minimum"]
        for class_id, entry in load_crosswalk()["classes"].items()
        if entry["restriction_minimum"] != "NONE"
    }


def auto_derivable() -> dict[str, dict[str, Any]]:
    """Upstream decision to its derivation record, for classes a detector produces."""
    out: dict[str, dict[str, Any]] = {}
    for class_id, entry in load_crosswalk()["classes"].items():
        derive = entry.get("auto_derive")
        if derive:
            out[derive["decision"]] = {**derive, "artifact_class": class_id}
    return out


def equivalents(class_id: str, vocabulary: str) -> tuple[str, ...]:
    """Equivalent terms for a class in another vocabulary; empty when there are none."""
    if vocabulary not in VOCABULARIES:
        raise ValueError(f"unknown vocabulary: {vocabulary}")
    entry = load_crosswalk()["classes"][class_id]
    return tuple(entry.get("vocabulary", {}).get(vocabulary, ()))


def ambiguous_equivalents(class_id: str, vocabulary: str) -> tuple[str, ...]:
    """Terms that could denote this class but are canonically assigned elsewhere.

    The older vocabularies are coarser than SATIM-A: one ``ZOOM_BLUR`` covers both
    sensor motion blur and display resampling. Recording the conflation keeps a reviewer
    of a legacy record from reading more precision into the term than it carries.
    """
    if vocabulary not in VOCABULARIES:
        raise ValueError(f"unknown vocabulary: {vocabulary}")
    entry = load_crosswalk()["classes"][class_id]
    return tuple(entry.get("vocabulary_ambiguous", {}).get(vocabulary, ()))


def resolve(term: str, vocabulary: str) -> str | None:
    """Map a term from another vocabulary back to its SATIM-A class, if any."""
    for class_id in load_crosswalk()["classes"]:
        if term in equivalents(class_id, vocabulary):
            return class_id
    return None


def unmapped_terms() -> set[str]:
    """Terms deliberately left without a SATIM-A equivalent."""
    groups = load_crosswalk()["deliberately_unmapped"]
    return {
        term
        for key, group in groups.items()
        if key != "description"
        for term in group["terms"]
    }
