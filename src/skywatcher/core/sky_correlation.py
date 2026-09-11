"""Fail-closed classification for sky-domain explanation candidates.

This module is intentionally source-agnostic. It classifies an already-computed
set of evidence gates; it does not perform identity resolution, ephemeris
calculation, or source discovery.
"""

from __future__ import annotations

from collections.abc import Mapping

ALLOWED_GATE_STATES = frozenset({"PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"})

# Time and visibility are always material for a physical sky-event explanation.
REQUIRED_GATES = ("time", "visibility")

# These are material when evidence exists. NOT_APPLICABLE is permitted only when
# the producing analysis explicitly establishes that the gate does not apply.
CONTEXT_GATES = (
    "location",
    "azimuth",
    "elevation",
    "trajectory",
    "duration",
    "appearance",
    "upstream_identity",
)

ALL_GATES = REQUIRED_GATES + CONTEXT_GATES


def classify_candidate(gates: Mapping[str, str]) -> str:
    """Return MATCHED, PARTIAL, CONTRADICTED, or UNRESOLVED.

    Rules are deliberately conservative:
    * missing/invalid gates are errors;
    * any FAIL contradicts the candidate;
    * required gates must PASS (N/A is not accepted for time/visibility);
    * MATCHED requires every contextual gate to be PASS or NOT_APPLICABLE;
    * otherwise some positive evidence plus UNKNOWN remains PARTIAL;
    * no positive evidence remains UNRESOLVED.
    """

    missing = [name for name in ALL_GATES if name not in gates]
    if missing:
        raise ValueError(f"missing gates: {', '.join(missing)}")

    invalid = {name: gates[name] for name in ALL_GATES if gates[name] not in ALLOWED_GATE_STATES}
    if invalid:
        raise ValueError(f"invalid gate states: {invalid}")

    if any(gates[name] == "FAIL" for name in ALL_GATES):
        return "CONTRADICTED"

    if any(gates[name] != "PASS" for name in REQUIRED_GATES):
        return "UNRESOLVED"

    contextual = [gates[name] for name in CONTEXT_GATES]
    if all(state in {"PASS", "NOT_APPLICABLE"} for state in contextual):
        return "MATCHED"

    if any(state == "PASS" for state in contextual):
        return "PARTIAL"

    return "UNRESOLVED"
