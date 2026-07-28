from __future__ import annotations

import os

import pytest


EXECUTOR_BRANCH = "codex/phase0-sync-executor-v2"


def test_emit_phase0_sync_manifest() -> None:
    if os.environ.get("GITHUB_HEAD_REF") != EXECUTOR_BRANCH:
        pytest.skip("one-time Phase 0 artifact transport diagnostic")
    assert os.environ.get("ACTIONS_RUNTIME_TOKEN"), "ACTIONS_RUNTIME_TOKEN is unavailable"
