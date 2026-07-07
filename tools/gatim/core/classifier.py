"""Conservative class and feature assignment for GATIM."""
from __future__ import annotations

from .confidence import score_candidate
from .grid import grid_id_for

FEATURE_TERMS = {
    "road": ["road", "camino", "carretera", "pr-", "trail", "sendero"],
    "water": ["river", "rio", "río", "lake", "lago", "laguna", "canal", "represa", "dam", "water"],
    "structure": ["hangar", "plant", "substation", "tower", "facility", "factory", "warehouse"],
    "terrain_cut": ["cut", "scar", "clearing", "quarry", "cantera", "excav", "trench"],
    "pad": ["pad", "helipad", "platform", "plataforma"],
}


def joined(row) -> str:
    return " ".join([row.source_file, row.source_dataset, row.title, row.note, row.tags, row.comment]).lower()


def classify(row) -> str:
    text = joined(row)
    source = row.source_dataset.lower()
    if "uap" in source:
        return "UAP_CASE_ANCHOR"
    if "road" in text or "camino" in text or "access" in text:
        return "ACCESS"
    if "ilap" in text or "review node" in text:
        return "ILAP"
    if any(term in text for term in ["substation", "plant", "tower", "aerostato", "airport", "aeropuerto", "hangar"]):
        return "INFRASTRUCTURE"
    return "TERRAIN_ANOMALY"


def visual_features(row) -> str:
    text = joined(row)
    found = [label for label, terms in FEATURE_TERMS.items() if any(term in text for term in terms)]
    return ";".join(found) if found else "unspecified"


def evidence_tier(row) -> str:
    if row.coord_status == "direct" and row.url:
        return "T2"
    return "T4"


def review_priority(row) -> str:
    cls = row.class_primary
    conf = float(row.confidence or 0)
    if row.coord_status != "direct":
        return "P3_GEOCODE"
    if cls in {"ILAP", "INFRASTRUCTURE"} and conf >= 0.75:
        return "P0_REVIEW"
    if cls in {"TERRAIN_ANOMALY", "ACCESS"} and conf >= 0.65:
        return "P1_REVIEW"
    if cls == "UAP_CASE_ANCHOR":
        return "P2_CONTEXT"
    return "P2_REVIEW"


def apply_classification(rows: list) -> list:
    for row in rows:
        row.class_primary = classify(row)
        row.evidence_tier = evidence_tier(row)
        row.visual_features = visual_features(row)
        row.grid_id = grid_id_for(row.lat, row.lon)
        row.confidence = f"{score_candidate(row):.2f}"
        row.review_priority = review_priority(row)
    return rows
