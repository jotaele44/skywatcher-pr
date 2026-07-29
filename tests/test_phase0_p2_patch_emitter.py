from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EMITTER_PATH = "tests/test_phase0_p2_patch_emitter.py"


def _replace_once(text: str, old: str, new: str, path: str) -> str:
    count = text.count(old)
    assert count == 1, f"{path}: expected one replacement target, found {count}"
    return text.replace(old, new, 1)


def _backend_test_addendum() -> str:
    return '''\n\ndef test_sort_rows_keeps_missing_values_last_in_both_directions():\n    rows = [\n        {"id": "missing-none", "created_date": None},\n        {"id": "older", "created_date": "2026-01-01"},\n        {"id": "missing-empty", "created_date": ""},\n        {"id": "newer", "created_date": "2026-02-01"},\n    ]\n\n    assert [row["id"] for row in main.sort_rows(rows, "created_date")] == [\n        "older",\n        "newer",\n        "missing-none",\n        "missing-empty",\n    ]\n    assert [row["id"] for row in main.sort_rows(rows, "-created_date")] == [\n        "newer",\n        "older",\n        "missing-none",\n        "missing-empty",\n    ]\n\n\ndef test_descending_sort_pagination_does_not_drop_recent_rows(monkeypatch):\n    rows = (\n        {"id": "missing", "created_date": None},\n        {"id": "old", "created_date": "2026-01-01"},\n        {"id": "new", "created_date": "2026-03-01"},\n        {"id": "middle", "created_date": "2026-02-01"},\n    )\n    monkeypatch.setitem(main.LOADERS, "ManualReviewItems", lambda: rows)\n\n    response = client.get(\n        "/api/entities/ManualReviewItems?sort=-created_date&limit=2"\n    )\n\n    assert response.status_code == 200\n    assert [row["id"] for row in response.json()] == ["new", "middle"]\n'''


def _satim_repeatability_tests() -> str:
    return '''from __future__ import annotations\n\nimport zipfile\nfrom pathlib import Path\n\nimport pytest\n\nfrom fr24 import satim_engine, satim_engine_core\n\nENGINES = (satim_engine, satim_engine_core)\n\n\ndef _write_zip(path: Path, files: dict[str, str]) -> None:\n    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:\n        for name, content in files.items():\n            archive.writestr(name, content)\n\n\n@pytest.mark.parametrize(\n    "engine",\n    ENGINES,\n    ids=lambda engine: engine.__name__.rsplit(".", 1)[-1],\n)\ndef test_zip_backed_runs_replace_previous_extraction(tmp_path, engine):\n    archive = tmp_path / "input.zip"\n    output = tmp_path / "run"\n    _write_zip(\n        archive,\n        {\n            "bundle/screenshots/first.txt": "first",\n            "bundle/stale.txt": "stale",\n        },\n    )\n\n    first_root = engine.prepare_input_root(archive, output)\n    assert (first_root / "screenshots" / "first.txt").read_text() == "first"\n    assert (first_root / "stale.txt").exists()\n\n    _write_zip(archive, {"bundle/screenshots/second.txt": "second"})\n    second_root = engine.prepare_input_root(archive, output)\n\n    assert second_root == first_root\n    assert (second_root / "screenshots" / "second.txt").read_text() == "second"\n    assert not (second_root / "screenshots" / "first.txt").exists()\n    assert not (second_root / "stale.txt").exists()\n\n\ndef test_satim_engine_mirror_extraction_parity(tmp_path):\n    archive = tmp_path / "input.zip"\n    _write_zip(\n        archive,\n        {\n            "bundle/screenshots/frame.txt": "frame",\n            "bundle/annotations.json": "{}",\n        },\n    )\n\n    snapshots = []\n    returned_roots = []\n    for engine in ENGINES:\n        output = tmp_path / engine.__name__.rsplit(".", 1)[-1]\n        root = engine.prepare_input_root(archive, output)\n        returned_roots.append(root.relative_to(output).as_posix())\n        snapshots.append(\n            {\n                item.relative_to(root).as_posix(): item.read_bytes()\n                for item in sorted(root.rglob("*"))\n                if item.is_file()\n            }\n        )\n\n    assert returned_roots == ["_input_unpacked/bundle"] * 2\n    assert snapshots[0] == snapshots[1]\n'''


def test_emit_phase0_p2_patch_manifest():
    if sys.version_info[:2] != (3, 12):
        pytest.skip("emit the deterministic patch manifest once on Python 3.12")

    patched: dict[str, str] = {}
    for path in ("fr24/satim_engine.py", "fr24/satim_engine_core.py"):
        text = (ROOT / path).read_text(encoding="utf-8")
        patched[path] = _replace_once(
            text,
            "    safe_extract_zip(source, target)\n",
            "    safe_extract_zip(source, target, replace=True)\n",
            path,
        )

    backend_path = "server/backend/main.py"
    backend = (ROOT / backend_path).read_text(encoding="utf-8")
    patched[backend_path] = _replace_once(
        backend,
        '''def sort_rows(rows, sort):\n    if not sort:\n        return rows\n    reverse = sort.startswith("-")\n    key = sort.lstrip("-")\n    return sorted(rows, key=lambda row: _sort_value(row.get(key)), reverse=reverse)\n''',
        '''def sort_rows(rows, sort):\n    if not sort:\n        return rows\n    reverse = sort.startswith("-")\n    key = sort.lstrip("-")\n    present = [row for row in rows if row.get(key) not in (None, "")]\n    missing = [row for row in rows if row.get(key) in (None, "")]\n    return sorted(\n        present,\n        key=lambda row: _sort_value(row.get(key)),\n        reverse=reverse,\n    ) + missing\n''',
        backend_path,
    )

    backend_test_path = "tests/test_backend_api_security.py"
    backend_tests = (ROOT / backend_test_path).read_text(encoding="utf-8")
    marker = "def test_sort_rows_keeps_missing_values_last_in_both_directions"
    assert marker not in backend_tests
    patched[backend_test_path] = backend_tests.rstrip() + _backend_test_addendum() + "\n"

    satim_test_path = "tests/test_satim_engine_repeatability.py"
    assert not (ROOT / satim_test_path).exists()
    patched[satim_test_path] = _satim_repeatability_tests()

    files = {}
    for path, content in sorted(patched.items()):
        raw = content.encode("utf-8")
        files[path] = {
            "content_b64": base64.b64encode(raw).decode("ascii"),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    payload = {
        "schema": "skywatcher.phase0.p2.patch.v1",
        "head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "base_tree": subprocess.check_output(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
        ).strip(),
        "delete_paths": [EMITTER_PATH],
        "files": files,
    }
    encoded = base64.b64encode(
        zlib.compress(json.dumps(payload, sort_keys=True).encode("utf-8"), level=9)
    ).decode("ascii")
    print("PHASE0_P2_MANIFEST_BEGIN")
    print(encoded)
    print("PHASE0_P2_MANIFEST_END")
    pytest.fail("intentional manifest emission; remove this test in the published tree")
