from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

ORDER = {
    "NONE": 0,
    "SPECTRAL_ONLY_DEGRADED": 1,
    "GEOMETRY_DEGRADED": 2,
    "OBJECT_LEVEL_PROHIBITED": 3,
    "ALL_INFERENCE_SUSPENDED": 4,
}
CLASS_MINIMUM = {
    "SATIM-A03": "OBJECT_LEVEL_PROHIBITED",
    "SATIM-A05": "GEOMETRY_DEGRADED",
    "SATIM-A06": "OBJECT_LEVEL_PROHIBITED",
    "SATIM-A07": "GEOMETRY_DEGRADED",
    "SATIM-A10": "SPECTRAL_ONLY_DEGRADED",
    "SATIM-A11": "ALL_INFERENCE_SUSPENDED",
    "SATIM-A12": "ALL_INFERENCE_SUSPENDED",
}


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
