"""Skywatcher's Launch Pad declaration (desktop/config.py).

The screen itself lives in the shared prii_desktop runtime; these tests keep the
declaration true to this repository. They skip when the installed runtime
predates the Launch Pad.
"""

import re
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

launchpad = pytest.importorskip("prii_desktop.launchpad")

from prii_desktop import DesktopConfig  # noqa: E402

from desktop import config  # noqa: E402

ROOT = Path(config.REPO_ROOT)


def _spec():
    return launchpad.launchpad_spec(DesktopConfig.from_module(config))


def test_declaration_is_valid_two_mode():
    spec = _spec()
    assert spec is not None and spec.has_modes
    # Operator relies on the backend's loopback rule, so it sets no credential.
    assert spec.operator.token_env is None


def test_start_pages_are_real_routes():
    routes = (ROOT / "frontend/src/App.jsx").read_text()
    for page in _spec().start_pages:
        assert f'path="{page.route}"' in routes, page.route


def test_guest_allow_list_is_exactly_the_read_only_posts():
    """Every non-GET route is either refused for a guest or a declared read."""
    sources = [
        (ROOT / "server/backend/main.py").read_text(),
        (ROOT / "server/backend/cameras_router.py").read_text(),
    ]
    declared = re.findall(
        r'@(?:app|router)\.(post|put|patch|delete)\(\s*"([^"]+)"', "\n".join(sources)
    )
    assert len(declared) == 7, declared  # a new write route must be classified here
    guard = launchpad.GuestGuard(None, _spec().guest_allow)
    passes = sorted(
        (method.upper(), path)
        for method, path in declared
        if any(
            (allowed is None or allowed == method.upper())
            and pattern.fullmatch(re.sub(r"\{[^}]+\}", "x", path))
            for allowed, pattern in guard.allow
        )
    )
    assert passes == [
        ("POST", "/api/entities/{entity_name}/filter"),
        ("POST", "/api/query"),
    ]


def test_options_bind_variables_the_backend_reads():
    code = "\n".join(
        path.read_text()
        for path in (
            ROOT / "server/backend/cameras_router.py",
            ROOT / "src/skywatcher/query/llm.py",
        )
    )
    for option in _spec().options:
        assert f'"{option.env}"' in code, option.env


def test_status_counts_archive_and_pending_submissions(tmp_path, monkeypatch):
    archive = tmp_path / "skywatcher.db"
    conn = sqlite3.connect(archive)
    conn.execute("CREATE TABLE flight_corpus_snapshots (id TEXT)")
    conn.executemany("INSERT INTO flight_corpus_snapshots VALUES (?)", [("a",), ("b",)])
    conn.commit()
    conn.close()
    cameras = tmp_path / "cameras"
    cameras.mkdir()
    conn = sqlite3.connect(cameras / "submissions.sqlite")
    conn.execute("CREATE TABLE submissions (id TEXT, status TEXT)")
    conn.executemany(
        "INSERT INTO submissions VALUES (?, ?)", [("1", "pending"), ("2", "approved")]
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("SKYWATCHER_DB", str(archive))
    monkeypatch.setenv("SKYWATCHER_SKY_CAMERAS_ROOT", str(cameras))

    rows = {row["label"]: row for row in config._launchpad_status()}

    assert rows["Reference data"]["status"] == "pass"
    assert rows["Flight archive"]["value"] == "2 snapshots"
    assert rows["Sky camera submissions"]["value"] == "1 pending"
    assert rows["Sky camera submissions"]["status"] == "warn"


def test_status_creates_nothing_when_stores_are_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("SKYWATCHER_DB", str(tmp_path / "none.db"))
    monkeypatch.setenv("SKYWATCHER_SKY_CAMERAS_ROOT", str(tmp_path / "none"))
    rows = {row["label"]: row for row in config._launchpad_status()}
    assert rows["Flight archive"]["value"] == "Empty"
    assert rows["Sky camera submissions"]["value"] == "None"
    assert list(tmp_path.iterdir()) == []
