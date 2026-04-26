"""
Entity normalisation and deduplication for GEO-PR-INT.

Handles vendor/contractor name cleaning, legal-suffix stripping,
cross-source deduplication, and fuzzy vendor matching.
"""

import logging
import re
from difflib import SequenceMatcher

import pandas as pd

logger = logging.getLogger(__name__)

_LEGAL_SUFFIXES = re.compile(
    r"\b(llc|inc|incorporated|corp|corporation|company|co|ltd|lp|llp|"
    r"associates|group|solutions|services|contractors|construction|"
    r"consulting|enterprises|international|technologies|tech|systems|"
    r"management|partners|partnership|authority|administration|"
    r"authority|department|office)\b\.?",
    re.IGNORECASE,
)

_PUNCT = re.compile(r"[,\.\-\/\(\)\"\'&]+")
_SPACES = re.compile(r"\s{2,}")


def normalise_entity_name(name: str) -> str:
    """Lowercase, strip legal suffixes, remove punctuation, collapse whitespace."""
    if not isinstance(name, str) or not name.strip():
        return ""
    s = name.lower().strip()
    s = _LEGAL_SUFFIXES.sub(" ", s)
    s = _PUNCT.sub(" ", s)
    s = _SPACES.sub(" ", s)
    return s.strip()


def build_entity_index(contracts: pd.DataFrame) -> dict[str, list[int]]:
    """Map normalised vendor name → list of row indices in contracts."""
    index: dict[str, list[int]] = {}
    if "recipient_name_norm" not in contracts.columns:
        contracts = contracts.copy()
        contracts["recipient_name_norm"] = contracts.get(
            "recipient_name", pd.Series("", index=contracts.index)
        ).apply(normalise_entity_name)

    for idx, norm in contracts["recipient_name_norm"].items():
        if norm:
            index.setdefault(norm, []).append(int(idx))
    return index


def deduplicate_contracts(df: pd.DataFrame) -> pd.DataFrame:
    """
    Group by recipient_name_norm, aggregate obligated_amount, keep latest award_date.

    Returns one row per unique normalised vendor with summed obligations.
    """
    if df.empty:
        return df

    df = df.copy()
    if "recipient_name_norm" not in df.columns:
        df["recipient_name_norm"] = df.get("recipient_name", "").apply(normalise_entity_name)

    if "obligated_amount" not in df.columns:
        df["obligated_amount"] = 0.0

    df["obligated_amount"] = pd.to_numeric(df["obligated_amount"], errors="coerce").fillna(0.0)

    # Coerce award_date so we can take a max
    if "award_date" in df.columns:
        df["award_date"] = pd.to_datetime(df["award_date"], errors="coerce")
    else:
        df["award_date"] = pd.NaT

    agg: dict = {
        "obligated_amount": "sum",
        "award_date": "max",
    }
    # Carry forward first occurrence of other useful columns
    for col in ["recipient_name", "awarding_agency_name", "naics_code", "psc_code",
                "lat", "lon", "geocode_method"]:
        if col in df.columns:
            agg[col] = "first"

    result = (
        df.groupby("recipient_name_norm", sort=False)
        .agg(agg)
        .reset_index()
    )
    logger.info(
        f"Entity dedup: {len(df)} → {len(result)} rows "
        f"({len(df) - len(result)} duplicates merged)"
    )
    return result


def match_vendor_to_ilap(vendor_norm: str, ilap_labels: list[str]) -> float:
    """
    Return the highest fuzzy similarity (0–1) between vendor_norm and any label
    in ilap_labels.  Uses difflib.SequenceMatcher — no new deps.
    """
    if not vendor_norm or not ilap_labels:
        return 0.0
    best = 0.0
    for label in ilap_labels:
        if not label:
            continue
        ratio = SequenceMatcher(None, vendor_norm, label.lower()).ratio()
        if ratio > best:
            best = ratio
    return best


def enrich_contracts_with_norms(df: pd.DataFrame) -> pd.DataFrame:
    """Add recipient_name_norm column if missing. Idempotent."""
    df = df.copy()
    if "recipient_name_norm" not in df.columns:
        df["recipient_name_norm"] = df.get(
            "recipient_name", pd.Series("", index=df.index)
        ).apply(normalise_entity_name)
    return df


def top_vendors_by_obligation(
    df: pd.DataFrame,
    n: int = 50,
) -> pd.DataFrame:
    """Return top-n vendors ranked by total obligated_amount."""
    if df.empty:
        return df
    df = enrich_contracts_with_norms(df)
    if "obligated_amount" not in df.columns:
        return df.head(n)

    grouped = (
        df.groupby("recipient_name_norm")["obligated_amount"]
        .sum()
        .reset_index()
        .sort_values("obligated_amount", ascending=False)
    )
    top_norms = set(grouped.head(n)["recipient_name_norm"])
    return df[df["recipient_name_norm"].isin(top_norms)].copy()
