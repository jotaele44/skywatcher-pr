"""Guards for the artifact crosswalk and the vocabularies it reconciles.

Six tables used to encode overlapping facts about the same twelve classes with nothing
keeping them in agreement: compound_artifacts.PRIORITY, the taxonomy's per-class
priority integer, restriction_gate.CLASS_MINIMUM, the taxonomy's restriction prose, and
four L5_* dicts in pipeline_chain. They now derive from one file. These tests pin that
the derivation is faithful and that the file cannot rot.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from skywatcher.satim.artifacts import crosswalk
from skywatcher.satim.artifacts.compound_artifacts import PRIORITY
from skywatcher.satim.artifacts.pipeline_chain import (
    L5_CLASS_ORIGIN_LAYER,
    L5_CLASS_RESTRICTION,
    L5_DECISION_TO_CLASS,
    L5_DECISION_TO_LIKELIHOOD,
)
from skywatcher.satim.artifacts.restriction_gate import CLASS_MINIMUM, ORDER

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_TAXONOMY = (
    REPO_ROOT / "src/skywatcher/satim/artifacts/artifact_taxonomy_v1.json"
)
SCHEMAS_TAXONOMY = REPO_ROOT / "schemas/artifact_taxonomy_v1.json"

ALL_CLASSES = tuple(f"SATIM-A{i:02d}" for i in range(1, 13))


def test_crosswalk_covers_exactly_the_twelve_taxonomy_classes() -> None:
    taxonomy = json.loads(PACKAGE_TAXONOMY.read_text(encoding="utf-8"))
    assert set(crosswalk.load_crosswalk()["classes"]) == {
        entry["id"] for entry in taxonomy["classes"]
    }
    assert set(crosswalk.class_ids()) == set(ALL_CLASSES)


def test_arbitration_order_is_preserved_exactly() -> None:
    """The refactor must not have reordered compound-artifact arbitration."""
    assert PRIORITY == (
        "SATIM-A12", "SATIM-A11", "SATIM-A03", "SATIM-A07", "SATIM-A05",
        "SATIM-A06", "SATIM-A10", "SATIM-A01", "SATIM-A04", "SATIM-A09",
        "SATIM-A02", "SATIM-A08",
    )


def test_restriction_minima_are_preserved_exactly() -> None:
    assert CLASS_MINIMUM == {
        "SATIM-A03": "OBJECT_LEVEL_PROHIBITED",
        "SATIM-A05": "GEOMETRY_DEGRADED",
        "SATIM-A06": "OBJECT_LEVEL_PROHIBITED",
        "SATIM-A07": "GEOMETRY_DEGRADED",
        "SATIM-A10": "SPECTRAL_ONLY_DEGRADED",
        "SATIM-A11": "ALL_INFERENCE_SUSPENDED",
        "SATIM-A12": "ALL_INFERENCE_SUSPENDED",
    }
    assert set(CLASS_MINIMUM.values()) <= set(ORDER)


def test_auto_derivation_tables_are_preserved_exactly() -> None:
    assert L5_DECISION_TO_CLASS == {
        "probable_tile_seam": "SATIM-A01",
        "probable_cloud_shadow": "SATIM-A09",
    }
    assert L5_DECISION_TO_LIKELIHOOD == {
        "probable_tile_seam": "tile_seam_likelihood",
        "probable_cloud_shadow": "cloud_shadow_likelihood",
    }
    assert L5_CLASS_ORIGIN_LAYER == {"SATIM-A01": "unresolved", "SATIM-A09": "atmosphere"}
    assert L5_CLASS_RESTRICTION == {
        "SATIM-A01": "GEOMETRY_DEGRADED",
        "SATIM-A09": "OBJECT_LEVEL_PROHIBITED",
    }


def test_every_auto_derived_request_meets_its_own_restriction_floor() -> None:
    """An auto-derivation must not request something the gate would reject."""
    for record in crosswalk.auto_derivable().values():
        minimum = CLASS_MINIMUM.get(record["artifact_class"], "NONE")
        assert ORDER[record["requested_restriction"]] >= ORDER[minimum], record


def test_every_auto_derivation_states_why_it_restricts() -> None:
    for decision, record in crosswalk.auto_derivable().items():
        assert record["rationale"].strip(), f"{decision} restricts without saying why"


def test_arbitration_rank_is_unique_and_dense() -> None:
    """Enforced at load, so a duplicate rank fails fast rather than silently reordering."""
    ranks = [
        entry["arbitration_rank"]
        for entry in crosswalk.load_crosswalk()["classes"].values()
    ]
    assert sorted(ranks) == list(range(12))


def test_taxonomy_priority_integer_is_not_a_total_order() -> None:
    """Documents why arbitration_rank exists rather than reusing the taxonomy field.

    If this ever starts failing, the taxonomy integers became unique and the crosswalk
    could in principle derive from them — but that is a deliberate decision to make, not
    something to discover through a mystery reordering.
    """
    taxonomy = json.loads(PACKAGE_TAXONOMY.read_text(encoding="utf-8"))
    priorities = [entry["priority"] for entry in taxonomy["classes"]]
    assert len(set(priorities)) < len(priorities), (
        "taxonomy priority integers are now unique; revisit the crosswalk's rationale"
    )


@pytest.mark.parametrize("vocabulary", crosswalk.VOCABULARIES)
def test_no_term_maps_to_two_classes(vocabulary: str) -> None:
    """An ambiguous crosswalk is worse than no crosswalk."""
    seen: dict[str, str] = {}
    for class_id in crosswalk.class_ids():
        for term in crosswalk.equivalents(class_id, vocabulary):
            assert term not in seen, (
                f"{vocabulary} term {term!r} maps to both {seen[term]} and {class_id}"
            )
            seen[term] = class_id


def test_round_trip_from_other_vocabularies() -> None:
    assert crosswalk.resolve("TILE_SEAM", "observation_class") == "SATIM-A01"
    assert crosswalk.resolve("MIXED_EPOCH", "tile_artifact") == "SATIM-A10"
    assert crosswalk.resolve("cloud_shadow", "tile_artifact_ledger") == "SATIM-A09"
    assert crosswalk.resolve("PARALLAX_OFFSET", "artifact_signal") == "SATIM-A08"
    assert crosswalk.resolve("UI_OVERLAY", "observation_class") is None


def test_coarse_terms_record_their_conflation() -> None:
    """The legacy vocabularies are coarser than SATIM-A; that must not be lost silently.

    ZOOM_BLUR and BLUR_EDGE each name blur without its cause, and
    ORTHO_MOSAIC_BOUNDARY conflates a seam with an orthorectification offset. Each is
    canonically assigned to one class, with the conflation recorded on the other.
    """
    assert crosswalk.ambiguous_equivalents("SATIM-A04", "tile_artifact") == ("ZOOM_BLUR",)
    assert crosswalk.ambiguous_equivalents("SATIM-A04", "artifact_signal") == ("BLUR_EDGE",)
    assert crosswalk.ambiguous_equivalents("SATIM-A07", "artifact_signal") == (
        "ORTHO_MOSAIC_BOUNDARY",
    )

    # Canonical assignment stays single-valued and deterministic.
    assert crosswalk.resolve("ZOOM_BLUR", "tile_artifact") == "SATIM-A05"
    assert crosswalk.resolve("BLUR_EDGE", "artifact_signal") == "SATIM-A03"
    assert crosswalk.resolve("ORTHO_MOSAIC_BOUNDARY", "artifact_signal") == "SATIM-A01"


def test_mapped_and_unmapped_terms_are_disjoint() -> None:
    """A term cannot be both deliberately unmapped and mapped."""
    mapped = {
        term
        for class_id in crosswalk.class_ids()
        for vocabulary in crosswalk.VOCABULARIES
        for term in crosswalk.equivalents(class_id, vocabulary)
    }
    assert not (mapped & crosswalk.unmapped_terms())


def test_every_real_vocabulary_term_is_mapped_or_explicitly_unmapped() -> None:
    """No term may be silently missing from the crosswalk.

    This is what stops the five vocabularies drifting apart again: adding an enum value
    anywhere forces a decision here.
    """
    finding_schema = json.loads(
        (
            REPO_ROOT
            / "skills/skywatcher-fr24-image-analysis/schemas/satim_finding.schema.json"
        ).read_text(encoding="utf-8")
    )
    tile_artifact = json.loads(
        (REPO_ROOT / "schemas/tile_artifact.schema.json").read_text(encoding="utf-8")
    )

    def artifact_class_enum(node: object) -> list[str]:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "artifact_class" and isinstance(value, dict) and "enum" in value:
                    return list(value["enum"])
                found = artifact_class_enum(value)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = artifact_class_enum(item)
                if found:
                    return found
        return []

    accounted = crosswalk.unmapped_terms()
    for vocabulary, terms in (
        ("observation_class", finding_schema["properties"]["observation_class"]["enum"]),
        ("tile_artifact", artifact_class_enum(tile_artifact)),
    ):
        for term in terms:
            assert crosswalk.resolve(term, vocabulary) or term in accounted, (
                f"{vocabulary} term {term!r} is neither mapped to a SATIM-A class nor "
                "listed under deliberately_unmapped"
            )


def test_duplicate_taxonomy_copies_stay_byte_identical() -> None:
    """schemas/ and the package each hold a copy, and nothing checked they agreed.

    Nothing reads the schemas/ copy today, so the two could have drifted indefinitely
    without any symptom until someone switched which one they loaded.
    """
    package = hashlib.sha256(PACKAGE_TAXONOMY.read_bytes()).hexdigest()
    schemas = hashlib.sha256(SCHEMAS_TAXONOMY.read_bytes()).hexdigest()
    assert package == schemas, (
        "artifact_taxonomy_v1.json copies have drifted between "
        "src/skywatcher/satim/artifacts/ and schemas/"
    )
