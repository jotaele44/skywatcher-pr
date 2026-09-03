"""Skywatcher query layer — grounded, read-only querying over craft profiles.

Top-of-stack consumer package. It reads persisted CraftProfiles (the
``craft_profiles`` table or ``profiles/craft/*.json``) and answers structured
intents deterministically; an optional Anthropic wrapper phrases those grounded
facts in natural language, never adding facts of its own and never inferring
intent/mission. Registered as the ``query`` bucket in
``skywatcher.core.module_boundaries`` (may consume core/satim/fpim/corrim; must
not import ``legacy``).
"""

from skywatcher.query.engine import Answer, QueryEngine

__all__ = ["Answer", "QueryEngine"]
