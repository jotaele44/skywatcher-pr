"""The `source_monitors` export stream (thehub-pr ADR 0013).

One row per source in registry/source_registry.yaml, carrying the same name,
family, tier, cadence, window and declared status that thehub-pr's registry reader
gives it, plus when the source last succeeded and how that is known: a run receipt
in data/source_run_state.json (RUN_RECEIPT), the newest `retrieved_at` among the
exported package's non-synthetic sources (OUTPUT_DERIVED), or neither
(NOT_RECORDED, null time).
"""
from __future__ import annotations

import hashlib
import importlib.machinery
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from scripts import federation_export as fe

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
REGISTRY = REPO / "registry" / "source_registry.yaml"
SCHEMA = REPO / "schemas" / "federation_source_monitor.schema.json"
# sha256 of thehub-pr schemas/federation_source_monitor.schema.json (1.0.0) at
# 0f62e4bdde10b5ac82787a329d6f15481ab9c7f0, the commit prii-export-utils is pinned to.
HUB_SCHEMA_SHA256 = "3cae40aacc4dff008cb0c97b4e5ab531648f6c262bc882627545fc32fb6c8e46"
SCALED_PACKAGE = REPO / "exports" / "fr24_bbox_icon_scaled_package"
SYNTHETIC_PACKAGE = REPO / "exports" / "examples" / "synthetic_airspace_package"
NOW = "2026-11-13T18:00:00Z"

# What thehub-pr's registry reader (src/hub/source_monitor.py, _parse_skywatcher, at
# 0f62e4b) yields for the committed registry: (name, producer_family, evidence_tier,
# cadence, cadence_window_seconds); its declared status is "unknown" for all. The
# Hub reads this producer only from the stream once it emits it, so none may change.
HUB_READER = {
    "adsb_exchange": ("aircraft event ingestion", "airspace", "T1", "realtime", 3600),
    "fr24_exports": ("aircraft pattern enrichment", "airspace", "T2", "event", None),
    "noaa_marinecadastre_baseline": ("maritime baseline context", "maritime", "T1", "static", None),
    "public_port_authority_updates": ("port context enrichment", "maritime", "T2", "unknown", None),
}
# Registry modes the hub reader maps to "unknown", as REGISTRY_MODE_CADENCE does.
MODES_WITHOUT_CADENCE = {"periodic_context"}


def _sources(package: Path) -> list[dict]:
    return json.loads((package / "sources.json").read_text())


def _rows(tmp_path: Path, sources: list[dict], **kwargs) -> dict[str, dict]:
    kwargs.setdefault("state_path", tmp_path / "no_source_run_state.json")
    rows = fe.build_source_monitors(sources, NOW, **kwargs)
    _assert_valid(rows)
    return {r["source_ref"]: r for r in rows}


def _assert_valid(rows: list[dict]) -> None:
    validator = Draft7Validator(json.loads(SCHEMA.read_text()))
    for row in rows:
        errors = sorted(e.message for e in validator.iter_errors(row))
        assert not errors, (row["source_ref"], errors)
        # The basis says how last_success_at is known; NOT_RECORDED means no time at all.
        assert (row["last_success_basis"] == "NOT_RECORDED") == (row["last_success_at"] is None)
    assert [r["source_ref"] for r in rows] == sorted(r["source_ref"] for r in rows)


def _registry(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "source_registry.yaml"
    path.write_text(text)
    return path


def test_vendored_schema_is_the_hub_contract():
    assert hashlib.sha256(SCHEMA.read_bytes()).hexdigest() == HUB_SCHEMA_SHA256


def test_rows_match_the_hub_registry_reader(tmp_path):
    rows = _rows(tmp_path, [])
    assert sorted(rows) == sorted(HUB_READER)
    for ref, (name, family, tier, cadence, window) in HUB_READER.items():
        row = rows[ref]
        got = (row["name"], row["producer_family"], row["evidence_tier"], row["cadence"],
               row["cadence_window_seconds"])
        assert got == (name, family, tier, cadence, window), ref
        assert row["declared_status"] == "unknown"
        assert row["source_url"] is None
        assert row["registry_path"] == "registry/source_registry.yaml"
        assert row["synthetic"] is False
        assert (row["created_at"], row["extracted_at"]) == (NOW, NOW)


def test_monitor_ids_are_deterministic(tmp_path):
    rows = _rows(tmp_path, [])
    for ref, row in rows.items():
        expected = "mon_" + hashlib.sha256(f"{fe.PRODUCER}|{ref}".encode()).hexdigest()[:32]
        assert row["monitor_id"] == expected
    assert _rows(tmp_path, []) == rows


def test_registry_reads_as_yaml_does():
    # The hub reader parses the registry with yaml.safe_load; the exporter uses the
    # repo's stdlib YAML-subset loader, which must read this file identically.
    yaml = pytest.importorskip("yaml")
    assert fe.load_simple_yaml(REGISTRY) == yaml.safe_load(REGISTRY.read_text())


def test_every_registry_mode_has_a_pinned_cadence():
    modes = {str(e.get("mode")).strip().lower()
             for entries in fe.load_simple_yaml(REGISTRY).values() if isinstance(entries, list)
             for e in entries}
    unmapped = modes - set(fe.REGISTRY_MODE_CADENCE) - MODES_WITHOUT_CADENCE
    assert not unmapped, f"map these modes as thehub-pr's reader does: {sorted(unmapped)}"


def test_every_committed_package_source_type_is_mapped():
    registry_ids = {e["id"] for entries in fe.load_simple_yaml(REGISTRY).values()
                    if isinstance(entries, list) for e in entries}
    assert set(fe.RETRIEVAL_SOURCE_TYPES.values()) <= registry_ids
    packages = sorted(REPO.glob("exports/**/sources.json"))
    assert packages
    types = {s.get("source_type") for path in packages for s in json.loads(path.read_text())
             if not str(s.get("provenance_status") or "").startswith("synthetic")}
    unmapped = types - set(fe.RETRIEVAL_SOURCE_TYPES)
    assert not unmapped, f"map these source types to a registry id: {sorted(unmapped)}"


def test_the_exported_packages_retrieval_is_output_derived(tmp_path):
    rows = _rows(tmp_path, _sources(SCALED_PACKAGE))
    fr24 = rows["fr24_exports"]
    assert (fr24["last_success_at"], fr24["last_success_basis"]) == ("2026-07-06T22:50:00Z", "OUTPUT_DERIVED")
    assert (fr24["last_attempt_at"], fr24["last_attempt_status"]) == (None, None)
    others = [r for ref, r in rows.items() if ref != "fr24_exports"]
    assert all(r["last_success_basis"] == "NOT_RECORDED" for r in others)


def test_a_synthetic_package_reports_nothing(tmp_path):
    rows = _rows(tmp_path, _sources(SYNTHETIC_PACKAGE))
    assert {(r["last_success_at"], r["last_success_basis"]) for r in rows.values()} == {(None, "NOT_RECORDED")}


def test_the_newest_real_mapped_retrieval_wins(tmp_path):
    sources = [
        {"source_type": "screenshot", "retrieved_at": "2026-07-06T22:50:00Z", "provenance_status": "operator_capture"},
        {"source_type": "screenshot", "retrieved_at": "2026-08-27T21:15:00+00:00", "provenance_status": "operator_capture"},
        # A naive time is read as UTC, as scripts/build_producer_package.py reads one.
        {"source_type": "screenshot", "retrieved_at": "2026-08-01T00:00:00", "provenance_status": "operator_capture"},
        {"source_type": "screenshot", "retrieved_at": "2026-11-01T00:00:00Z", "provenance_status": "synthetic_fixture"},
        {"source_type": "screenshot", "retrieved_at": "not a time", "provenance_status": "operator_capture"},
        {"source_type": "screenshot", "provenance_status": "operator_capture"},
        # Not mapped to a registry id: ADS-B rows may come from OpenSky, not ADS-B Exchange.
        {"source_type": "adsb", "retrieved_at": "2026-11-02T00:00:00Z", "provenance_status": "operator_capture"},
    ]
    rows = _rows(tmp_path, sources)
    assert rows["fr24_exports"]["last_success_at"] == "2026-08-27T21:15:00Z"
    assert rows["adsb_exchange"]["last_success_basis"] == "NOT_RECORDED"


def test_run_receipts_and_outputs_resolve_by_recency(tmp_path):
    from prii_export_utils import record_run

    state = tmp_path / "source_run_state.json"
    record_run(state, "fr24_exports", "success", at="2026-07-10T00:00:00Z")
    record_run(state, "adsb_exchange", "success", at="2026-11-12T10:00:00Z")
    record_run(state, "adsb_exchange", "failure", at="2026-11-13T10:00:00Z")
    rows = _rows(tmp_path, _sources(SCALED_PACKAGE), state_path=state)
    # The receipt (07-10) is newer than the package's retrieval (07-06).
    fr24 = rows["fr24_exports"]
    assert (fr24["last_success_at"], fr24["last_success_basis"]) == ("2026-07-10T00:00:00Z", "RUN_RECEIPT")
    assert (fr24["last_attempt_at"], fr24["last_attempt_status"]) == ("2026-07-10T00:00:00Z", "success")
    # A failed latest attempt keeps the last success.
    adsb = rows["adsb_exchange"]
    assert (adsb["last_success_at"], adsb["last_success_basis"]) == ("2026-11-12T10:00:00Z", "RUN_RECEIPT")
    assert (adsb["last_attempt_at"], adsb["last_attempt_status"]) == ("2026-11-13T10:00:00Z", "failure")

    older = tmp_path / "older_state.json"
    record_run(older, "fr24_exports", "success", at="2026-07-01T00:00:00Z")
    fr24 = _rows(tmp_path, _sources(SCALED_PACKAGE), state_path=older)["fr24_exports"]
    assert (fr24["last_success_at"], fr24["last_success_basis"]) == ("2026-07-06T22:50:00Z", "OUTPUT_DERIVED")


def test_normalisation_follows_the_hub_reader(tmp_path):
    registry = _registry(tmp_path, "\n".join([
        "schema_note: not a source list",
        "airspace:",
        "  - id: a",
        "    tier: t3",
        "    mode: Batch_File",
        "    use:   aircraft pattern enrichment",
        "  - id: b",
        "    tier: T9",
        "    mode: historical_baseline",
        "maritime:",
        "  - id: c",
        "    mode: periodic_context",
        "",
    ]))
    rows = _rows(tmp_path, [], registry_path=registry)
    assert sorted(rows) == ["a", "b", "c"]
    assert (rows["a"]["evidence_tier"], rows["a"]["cadence"], rows["a"]["name"]) == ("T3", "event", "aircraft pattern enrichment")
    assert (rows["b"]["evidence_tier"], rows["b"]["cadence"], rows["b"]["name"]) == (None, "static", "b")
    assert (rows["c"]["evidence_tier"], rows["c"]["cadence"], rows["c"]["cadence_window_seconds"]) == (None, "unknown", None)
    assert rows["c"]["producer_family"] == "maritime"


@pytest.mark.parametrize("text", [
    "airspace:\n  - id: a\n    mode: batch_file\nmaritime:\n  - id: a\n    mode: batch_file\n",
    "airspace:\n  - id: a\n  - mode: batch_file\n",
])
def test_duplicate_or_missing_ids_fail(tmp_path, text):
    with pytest.raises(ValueError):
        fe.build_source_monitors([], NOW, registry_path=_registry(tmp_path, text),
                                 state_path=tmp_path / "none.json")


def test_package_lists_the_stream_and_its_manifest_validates(tmp_path):
    rows = fe.build_source_monitors(_sources(SCALED_PACKAGE), NOW, state_path=tmp_path / "none.json")
    manifest_path = fe.write_package({"source_monitors": rows}, tmp_path / "pkg", "test", NOW)
    manifest = json.loads(manifest_path.read_text())
    [entry] = manifest["files"]
    assert (entry["stream"], entry["filename"]) == ("source_monitors", "source_monitors.jsonl")
    assert entry["schema_id"] == "federation_source_monitor.schema.json"
    assert entry["record_count"] == len(rows) == len(HUB_READER)
    body = (tmp_path / "pkg" / "source_monitors.jsonl").read_bytes()
    assert entry["sha256"] == hashlib.sha256(body).hexdigest()
    schema = json.loads((REPO / "schemas" / "federation_export_manifest.schema.json").read_text())
    assert not list(Draft7Validator(schema).iter_errors(manifest))


def test_the_exporter_script_writes_the_stream(tmp_path):
    # Run as the Hub and operators do, through scripts/prii_export_utils.py.
    out = tmp_path / "federation"
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "federation_export.py"), "--package", str(SCALED_PACKAGE),
         "--out", str(out), "--mode", "production"],
        capture_output=True, text=True, cwd=REPO,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((out / "manifest.json").read_text())
    assert [f["stream"] for f in manifest["files"]][-1] == "source_monitors"
    rows = [json.loads(line) for line in (out / "source_monitors.jsonl").read_text().splitlines()]
    _assert_valid(rows)
    assert {r["source_ref"]: r["last_success_basis"] for r in rows}["fr24_exports"] == "OUTPUT_DERIVED"


def _python(code: str, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *flags, "-c", code], capture_output=True, text=True, cwd=REPO)


def test_the_shim_keeps_its_ids_and_reaches_the_pinned_package():
    # scripts/ is first on sys.path when the exporter runs as a script, so
    # scripts/prii_export_utils.py shadows the pinned package. Its own helpers stay
    # as they were (ids depend on them); other names come from the package.
    code = "\n".join([
        "import hashlib, sys",
        "from pathlib import Path",
        f"sys.path.insert(0, {str(SCRIPTS)!r})",
        "import prii_export_utils as shim",
        f"assert Path(shim.__file__).resolve() == Path({str(SCRIPTS / 'prii_export_utils.py')!r})",
        "assert shim.fid('ent', 'a', None) == 'ent_' + hashlib.sha256(b'a|').hexdigest()[:32]",
        "assert shim.norm('Río Grande') == 'rio_grande'",
        "assert shim.source_monitor_row.__module__ == 'prii_export_utils.source_monitor'",
        "assert shim.resolve_last_success(None, None) == (None, 'NOT_RECORDED')",
        "assert sys.modules['prii_export_utils'] is shim",
        "try:",
        "    shim.no_such_helper",
        "except AttributeError:",
        "    pass",
        "else:",
        "    raise AssertionError('unknown names must raise AttributeError')",
    ])
    result = _python(code)
    assert result.returncode == 0, result.stderr


def test_the_pinned_package_loads_from_an_archive(tmp_path):
    # A frozen build can bundle the pinned package in an archive with no source file
    # on disk, so the shim imports it with the loader its finder returns. A zip on
    # sys.path is the same case.
    search = [p for p in sys.path if Path(p or ".").resolve() != SCRIPTS]
    spec = importlib.machinery.PathFinder.find_spec("prii_export_utils", search)
    assert spec is not None and spec.submodule_search_locations
    package = Path(next(iter(spec.submodule_search_locations)))
    archive = tmp_path / "pinned.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in sorted(package.glob("*.py")):
            zf.write(path, f"prii_export_utils/{path.name}")
    code = "\n".join([
        "import sys",
        f"sys.path[:0] = [{str(SCRIPTS)!r}, {str(archive)!r}]",
        "import prii_export_utils as shim",
        "assert shim.norm('Río Grande') == 'rio_grande'",
        "assert shim.source_monitor_row.__module__ == 'prii_export_utils.source_monitor'",
        "assert sys.modules['prii_export_utils'] is shim",
    ])
    # -S: no site-packages, so the zip is the only place the pinned package can come from.
    result = _python(code, "-S")
    assert result.returncode == 0, result.stderr
