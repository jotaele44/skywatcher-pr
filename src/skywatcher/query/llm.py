"""Natural-language wrapper over the deterministic QueryEngine.

Reuses the ``anthropic`` client pattern from ``scripts/fr24_vision_ingest.py``.
The engine assembles grounded context; the LLM only *phrases* that context in
natural language — it is never a source of facts and must not infer intent.

Graceful degradation: with no ``ANTHROPIC_API_KEY`` (or the ``anthropic``
package not installed), ``ask()`` returns the engine's deterministic text
answer, so the query capability works fully offline / in CI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from skywatcher.query.engine import Answer, QueryEngine

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = (
    "You are Skywatcher's airspace-data query assistant. Answer ONLY using the "
    "GROUNDED CONTEXT provided below — never from prior knowledge or assumption. "
    "You must NOT infer or state any aircraft's intent, mission, or purpose; if the "
    "context marks a mission as non-authoritative, do not present it as fact. Cite "
    "the profile field behind each fact. Surface the confidence grade and any "
    "coverage gaps or caps. If the context is insufficient to answer, say "
    '"Insufficient evidence in the current profiles" and state what is missing. '
    "Everything you report is a review-gated candidate, not a confirmed finding."
)


def _context_block(answer: Answer) -> str:
    return json.dumps(answer.to_dict(), indent=2, ensure_ascii=False)


def ask(
    prompt: str,
    *,
    db_path: Path | None = None,
    profile_dir: Path | None = None,
    model: str = DEFAULT_MODEL,
    engine: QueryEngine | None = None,
    api_key: str | None = None,
    _client=None,
) -> str:
    """Answer a natural-language prompt, grounded on the QueryEngine.

    Returns the LLM's phrasing when a key + the ``anthropic`` SDK are available,
    otherwise the engine's deterministic text (identical facts, terser prose).
    ``_client`` is an injection seam for tests (no live call).
    """
    engine = engine or QueryEngine(
        db_path=db_path,
        profile_dir=profile_dir or QueryEngine().profile_dir,
    )
    answer = engine.answer(prompt)

    client = _client or _build_client(api_key)
    if client is None:
        # Offline / no key: deterministic answer is the grounded truth.
        return answer.to_text()

    message = (
        f"USER QUESTION:\n{prompt}\n\n"
        f"GROUNDED CONTEXT (the only facts you may use):\n{_context_block(answer)}"
    )
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": message}],
        )
        return _extract_text(response) or answer.to_text()
    except Exception:
        # Any transport/SDK error falls back to the deterministic answer.
        return answer.to_text()


def _build_client(api_key: str | None):
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic.Anthropic(api_key=key)


def _extract_text(response) -> str:
    parts = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()
