"""Rule-based GATIM class, feature, evidence, confidence, and priority assignment."""
from __future__ import annotations

FEATURE_TERMS = {
    "road": ["road", "camino", "carretera", "pr-", "trail", "sendero"],
    "water": ["river", "rio", "río", "lake", "lago", "laguna", "canal", "represa", "dam", "water"],
    "structure": ["bunker", "hangar", "plant", "substation", "tower", "facility", "factory", "warehouse"],
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
    if "narnia" in text or "road" in text or "camino" in text:
        return "ACCESS"
    if "confirmed ilap" in text or "dumb" in source or "bunker" in text or "subsurface" in text:
        return "ILAP"
    if any(term in text for term in ["substation", "plant", "tower", "aerostato", "airport", "aeropuerto", "hangar"]):
        return "INFRASTRUCTURE"
    return "TERRAIN_ANOMALY"


def visual_features(row) -> str:
    text = joined(row)
    found = []
    for label, terms in FEATURE_TERMS.items():
        if any(term in text for term in terms):
            found.append(label)
    return ";".join(found) if found else "unspecified"


def evidence_tier(row) -> str:
    # This is a seed-candidate tier, not a claim-confirmation tier.
    if row.coord_status == "direct" and row.url:
        return "T2"
    return "T4"


def grid_id(row, precision: int = 3) -> str:
    try:
        lat = float(row.lat)
        lon = float(row.lon)
    except (TypeError, ValueError):
        return "NO_GRID"
    return f"GRID_{round(lat, precision):.{precision}f}_{round(lon, precision):.{precision}f}"


def confidence(row) -> float:
    score = 0.25
    if row.coord_status == "direct":
        score += 0.30
    if row.url:
        score += 0.10
    if row.note or row.tags:
        score += 0.10
    if row.dedupe_cluster_size and row.dedupe_cluster_size.isdigit() and int(row.dedupe_cluster_size) > 1:
        score += 0.10
    if visual_features(row) != "unspecified":
        score += 0.10
    return min(score, 0.95)


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
        row.grid_id = grid_id(row)
        row.confidence = f"{confidence(row):.2f}"
        row.review_priority = review_priority(row)
    return rows
