"""Maintainer scripts for Sky Cameras: liveness checker and catalog promotion (offline)."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from skywatcher.core.cameras import SubmissionInput, SubmissionStore, load_municipios

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "reference" / "sky_cameras" / "cameras.v1.json"
MUNICIPIOS = load_municipios(ROOT / "data" / "geo" / "pr_municipios_boundaries.json")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load("check_sky_cameras")
promote = _load("promote_sky_camera")


def test_check_classifies_offline_marker_and_dead_embed(monkeypatch):
    pages = {
        "https://a.example/cam": (200, b"<html>live</html>"),
        "https://b.example/cam": (200, b"<p><strong>OFFLINE</strong></p>"),
        "https://c.example/cam": (404, b""),
        "https://d.example/cam": (403, b""),
    }

    def fake_fetch(url, timeout):
        if "oembed" in url:
            return (404, b"") if "deadvideo01" in url else (200, b"{}")
        return pages[url]

    monkeypatch.setattr(check, "_fetch", fake_fetch)
    assert check.check_camera({"page_url": "https://a.example/cam", "embed": None})["status"] == "online"
    assert check.check_camera({"page_url": "https://b.example/cam", "embed": None})["status"] == "offline"
    assert check.check_camera({"page_url": "https://c.example/cam", "embed": None})["status"] == "offline"
    assert check.check_camera({"page_url": "https://d.example/cam", "embed": None})["status"] == "unknown"
    dead = {"page_url": "https://a.example/cam", "embed": {"kind": "youtube", "video_id": "deadvideo01"}}
    assert check.check_camera(dead)["status"] == "offline"


def test_check_writes_status(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(check, "_fetch", lambda url, timeout: (200, b"ok"))
    assert check.main(["--runtime-root", str(tmp_path)]) == 0
    status = json.loads((tmp_path / "status.json").read_text())
    assert set(status["cameras"]) == {row["id"] for row in json.loads(CATALOG.read_text())["cameras"]}


def _approved(store: SubmissionStore, **overrides) -> str:
    data = SubmissionInput(
        kind=overrides.pop("kind", "camera_link"),
        title="Lago Carite overlook",
        url=overrides.pop("url", "https://example.org/carite"),
        categories=["lake", "mountain"],
        municipality="Cayey",
        lat=18.07,
        lon=-66.06,
        license="display-only",
        attest_rights=True,
        attest_consent=True,
    )
    row = store.create(data, MUNICIPIOS)
    store.decide(row["id"], "approved")
    return row["id"]


def test_promote_appends_valid_entry(tmp_path):
    catalog = tmp_path / "cameras.v1.json"
    shutil.copy(CATALOG, catalog)
    store = SubmissionStore(tmp_path / "rt")
    submission_id = _approved(store)
    assert promote.main([submission_id, "--runtime-root", str(tmp_path / "rt"), "--catalog", str(catalog)]) == 0
    added = json.loads(catalog.read_text())["cameras"][-1]
    assert added["id"] == "cayey-lago-carite-overlook"
    assert added["embed"] is None and added["added_by"] == "community"


def test_promote_refuses_pending(tmp_path):
    store = SubmissionStore(tmp_path / "rt")
    row = store.create(
        SubmissionInput(kind="camera_link", title="x", url="https://example.org/x", categories=["sky"],
                        license="display-only", attest_rights=True, attest_consent=True),
        MUNICIPIOS,
    )
    with pytest.raises(SystemExit):
        promote.main([row["id"], "--runtime-root", str(tmp_path / "rt"), "--catalog", str(tmp_path / "c.json")])
