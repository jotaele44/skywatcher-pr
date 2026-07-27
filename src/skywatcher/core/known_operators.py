"""Exact aircraft-identifier registry with explicit provenance state.

Legacy entries are retained only as identifiers. No owner, operator, role, mission,
or operating-pattern field is promoted into the active profile until that field has
source URI, source record ID, capture time, and content hash provenance.
"""
from __future__ import annotations

IDENTIFIER_ALIASES: dict[str, str] = {}


def _legacy(identifier: str) -> dict:
    return {
        "identifier": identifier,
        "verified_fields": {},
        "provenance": {
            "status": "unverified_legacy_registry",
            "source_uri": None,
            "source_record_id": None,
            "captured_at": None,
            "sha256": None,
        },
    }


KNOWN_OPERATORS = {
    identifier: _legacy(identifier)
    for identifier in (
        "N5854Z",
        "C6062",
        "N767PD",
        "N684JB",
        "N911PR",
        "N304NG",
        "N448CB",
        "N229AE",
        "N87TV",
        "N521PR",
        "N172FA",
        "N388DR",
        "N960PR",
        "N741LE",
    )
}
