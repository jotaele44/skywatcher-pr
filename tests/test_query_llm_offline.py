"""LLM wrapper: grounded, degrades offline, never a live call in CI."""

import sqlite3
from pathlib import Path

import pytest

from skywatcher.fpim.craft_profile import (
    CraftProfileBuilder,
    ensure_tables,
    upsert_profile,
)
from skywatcher.query import llm
from skywatcher.query.engine import QueryEngine


@pytest.fixture
def engine(rlsm_db):
    conn = sqlite3.connect(rlsm_db)
    ensure_tables(conn)
    b = CraftProfileBuilder(db_path=Path(rlsm_db))
    for reg in b.registrations(conn):
        upsert_profile(conn, b.build_one(conn, reg))
    conn.commit()
    conn.close()
    return QueryEngine(db_path=Path(rlsm_db))


def test_degrades_to_deterministic_without_key(engine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = llm.ask("home base for N5854Z", engine=engine, api_key=None)
    # Identical to the deterministic engine text.
    assert out == engine.answer("home base for N5854Z").to_text()
    assert "SJU" in out or "Luis Muñoz Marín" in out


def test_system_prompt_encodes_doctrine():
    p = llm.SYSTEM_PROMPT.lower()
    assert "only" in p and "grounded context" in p
    assert "not infer" in p and ("intent" in p or "mission" in p)
    assert "cite" in p


class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, captured):
        self._captured = captured

    def create(self, **kwargs):
        self._captured.update(kwargs)
        return _FakeResponse("PHRASED: grounded answer with citation and confidence.")


class _FakeClient:
    def __init__(self):
        self.captured = {}
        self.messages = _FakeMessages(self.captured)


def test_injected_client_is_used_and_grounded(engine):
    client = _FakeClient()
    out = llm.ask("home base for N5854Z", engine=engine, _client=client)
    assert out.startswith("PHRASED:")
    # The grounded context (the engine's Answer) is passed to the model, and the
    # system prompt is the doctrine prompt.
    assert client.captured["system"] == llm.SYSTEM_PROMPT
    user_msg = client.captured["messages"][0]["content"]
    assert "GROUNDED CONTEXT" in user_msg
    assert "home_base" in user_msg


def test_client_error_falls_back_to_deterministic(engine):
    class _Boom:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("network down")

    out = llm.ask("home base for N5854Z", engine=engine, _client=_Boom())
    assert out == engine.answer("home base for N5854Z").to_text()
