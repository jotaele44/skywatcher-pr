"""Backend/GUI parity for the analysis registry.

The federation rule is that analysis capability is not complete until it is reachable
through the shipped interface. This repo has no automated parity gate on main — the
harness lives in unmerged PR #154 — and the two sides are hand-maintained mirrors that
nothing compares: `server.backend.main.LOADERS` and the `ENTITIES` map in
`frontend/src/lib/SkywatcherData.jsx` both list the same names, and the comment in
main.py ("Declared by the dashboard but with no committed source yet") shows the backend
list was transcribed from the GUI by hand.

`Promise.allSettled` in SkywatcherData swallows a 404, so a name present on one side and
absent on the other renders as a silently empty table rather than an error. These tests
close that specific gap for the analysis registry, and are deliberately stdlib-only —
the frontend is parsed with a regex, the same approach the repo's other cross-language
validators take rather than adding a JS toolchain dependency to the Python suite.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from skywatcher.core.lenses import load_default_registries

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND = REPO_ROOT / "frontend" / "src"
DATA_PROVIDER = FRONTEND / "lib" / "SkywatcherData.jsx"
APP_JSX = FRONTEND / "App.jsx"
SIDEBAR = FRONTEND / "components" / "skywatcher" / "Sidebar.jsx"
PAGE = FRONTEND / "pages" / "AnalysisLenses.jsx"

ANALYSIS_ENTITIES = {"AnalysisLenses", "AnalysisObjectives", "LensCoverage"}
ANALYSIS_ROUTE = "/analysis"


def _frontend_entities() -> set[str]:
    """Entity names the GUI requests, from the ENTITIES map."""
    text = DATA_PROVIDER.read_text(encoding="utf-8")
    block = re.search(r"const ENTITIES\s*=\s*\{(.*?)\};", text, re.DOTALL)
    assert block, "could not locate the ENTITIES map in SkywatcherData.jsx"
    return set(re.findall(r':\s*"([A-Za-z]+)"', block.group(1)))


def _backend_loaders() -> set[str]:
    from server.backend.main import LOADERS

    return set(LOADERS)


def test_every_entity_the_gui_requests_is_served_by_the_backend() -> None:
    """A GUI-only name renders an empty table instead of an error — catch it here."""
    missing = _frontend_entities() - _backend_loaders()
    assert not missing, (
        f"frontend requests entities the backend does not serve: {sorted(missing)}"
    )


def test_analysis_entities_are_present_on_both_sides() -> None:
    assert _backend_loaders() >= ANALYSIS_ENTITIES
    assert _frontend_entities() >= ANALYSIS_ENTITIES


def test_analysis_page_is_routed_and_discoverable() -> None:
    """Reachable by a normal user: a route alone is a hidden URL, not a workflow."""
    assert PAGE.is_file(), "AnalysisLenses.jsx is missing"

    app = APP_JSX.read_text(encoding="utf-8")
    assert f'path="{ANALYSIS_ROUTE}"' in app, "no /analysis route registered"
    assert "AnalysisLenses" in app, "AnalysisLenses page not imported by App.jsx"

    sidebar = SIDEBAR.read_text(encoding="utf-8")
    assert f'to: "{ANALYSIS_ROUTE}"' in sidebar, (
        "/analysis has a route but no sidebar entry, so it is only reachable by typing "
        "the URL — that is not a discoverable workflow"
    )


def test_registry_endpoint_serves_every_registered_lens() -> None:
    """The GUI must see exactly the lenses the registry holds, not a subset."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from server.backend.main import app

    payload = TestClient(app).get("/api/analysis/registry").json()
    assert payload["available"] is True

    lenses, objectives = load_default_registries()
    assert {row["lens_id"] for row in payload["lenses"]} == set(lenses.lens_ids())
    assert {row["profile_id"] for row in payload["objectives"]} == set(
        objectives.profile_ids()
    )


def test_served_lens_carries_what_the_page_renders() -> None:
    """Pin the fields the page reads, so a backend trim does not blank a column."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from server.backend.main import app

    payload = TestClient(app).get("/api/analysis/registry").json()
    for row in payload["lenses"]:
        for field in (
            "lens_id",
            "name",
            "owner",
            "stage",
            "status",
            "objective",
            "required_parameters",
            "optional_parameters",
            "emits",
        ):
            assert field in row, f"{row.get('lens_id')} missing {field}"
        for parameter in row["optional_parameters"]:
            # The page shows this as the tooltip on an optional parameter; an empty one
            # would render a chip that explains nothing.
            assert parameter["degraded_behavior"]


def test_page_does_not_hardcode_the_lens_vocabulary() -> None:
    """The whole point is that adding a lens needs no frontend edit.

    Every other vocabulary in this dashboard is a JSX literal. If lens ids start
    appearing in the page source, that regression has happened.
    """
    page = PAGE.read_text(encoding="utf-8")
    lenses, _ = load_default_registries()
    for lens_id in lenses.lens_ids():
        assert lens_id not in page, (
            f"{lens_id} is hardcoded in AnalysisLenses.jsx; the page must render "
            "whatever the registry endpoint returns"
        )
    assert "/analysis/registry" in page, "the page must fetch the registry"


def test_threshold_statuses_the_page_styles_cover_what_the_registry_emits() -> None:
    """An unstyled status silently falls back to muted, hiding PROHIBITED as neutral."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from server.backend.main import app

    payload = TestClient(app).get("/api/analysis/registry").json()
    served = {row["status"] for row in payload["thresholds"]}

    page = PAGE.read_text(encoding="utf-8")
    block = re.search(r"const THRESHOLD_TONE\s*=\s*\{(.*?)\};", page, re.DOTALL)
    assert block, "could not locate THRESHOLD_TONE in AnalysisLenses.jsx"
    styled = set(re.findall(r"([A-Z_]+):", block.group(1)))

    assert served <= styled, f"threshold status(es) with no tone mapping: {served - styled}"


def test_coverage_reports_validate_against_the_published_schema() -> None:
    """Whatever the LensCoverage entity serves must match the contract."""
    jsonschema = pytest.importorskip("jsonschema")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from server.backend.main import app

    schema = json.loads(
        (REPO_ROOT / "schemas/analysis_coverage_report_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    for row in TestClient(app).get("/api/entities/LensCoverage").json():
        payload = {k: v for k, v in row.items() if k not in ("id", "path")}
        jsonschema.validate(payload, schema)
