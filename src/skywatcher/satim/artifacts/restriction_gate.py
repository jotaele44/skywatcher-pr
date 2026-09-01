from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .crosswalk import restriction_minimums

ORDER = {
    "NONE": 0,
    "SPECTRAL_ONLY_DEGRADED": 1,
    "GEOMETRY_DEGRADED": 2,
    "OBJECT_LEVEL_PROHIBITED": 3,
    "ALL_INFERENCE_SUSPENDED": 4,
}

# Sourced from artifact_crosswalk_v1.json rather than restated here. This table used to
# duplicate the taxonomy's per-class restriction prose with nothing keeping the two in
# agreement. Same values as before; single origin now.
CLASS_MINIMUM = restriction_minimums()


@dataclass(frozen=True)
class RestrictionDecision:
    restriction: str
    allowed: bool
    reason: str


class InterpretationRestrictionGate:
    def minimum_for(self, classes: Iterable[str]) -> str:
        result = "NONE"
        for c in classes:
            candidate = CLASS_MINIMUM.get(c, "NONE")
            if ORDER[candidate] > ORDER[result]:
                result = candidate
        return result

    def enforce(
        self,
        classes: Iterable[str],
        requested: str | None = None,
        reviewer_override: bool = False,
        override_reason: str | None = None,
    ) -> RestrictionDecision:
        minimum = self.minimum_for(classes)
        requested = requested or minimum
        if requested not in ORDER:
            raise ValueError(f"unknown restriction: {requested}")
        if ORDER[requested] < ORDER[minimum]:
            if not reviewer_override or not override_reason:
                return RestrictionDecision(
                    minimum, False, "requested restriction would weaken mandatory gate"
                )
            return RestrictionDecision(
                requested, True, f"reviewer override: {override_reason}"
            )
        return RestrictionDecision(requested, True, "restriction satisfies mandatory gate")
