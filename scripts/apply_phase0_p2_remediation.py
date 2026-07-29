from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "agent/repository-hardening-phase-0"
RESTORE_WORKFLOW_FROM = "57f98ff37180d223a799aef01ac66ebd5d489484"


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement target, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_backend_tests() -> None:
    path = ROOT / "tests/test_backend_api_security.py"
    text = path.read_text(encoding="utf-8")
    marker = "def test_sort_rows_keeps_missing_values_last_in_both_directions"
    if marker in text:
        raise RuntimeError("backend null-last regressions already exist")
    text = text.rstrip() + '''


def test_sort_rows_keeps_missing_values_last_in_both_directions():
    rows = [
        {"id": "missing-none", "created_date": None},
        {"id": "older", "created_date": "2026-01-01"},
        {"id": "missing-empty", "created_date": ""},
        {"id": "newer", "created_date": "2026-02-01"},
    ]

    assert [row["id"] for row in main.sort_rows(rows, "created_date")] == [
        "older",
        "newer",
        "missing-none",
        "missing-empty",
    ]
    assert [row["id"] for row in main.sort_rows(rows, "-created_date")] == [
        "newer",
        "older",
        "missing-none",
        "missing-empty",
    ]


def test_descending_sort_pagination_does_not_drop_recent_rows(monkeypatch):
    rows = (
        {"id": "missing", "created_date": None},
        {"id": "old", "created_date": "2026-01-01"},
        {"id": "new", "created_date": "2026-03-01"},
        {"id": "middle", "created_date": "2026-02-01"},
    )
    monkeypatch.setitem(main.LOADERS, "ManualReviewItems", lambda: rows)

    response = client.get(
        "/api/entities/ManualReviewItems?sort=-created_date&limit=2"
    )

    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == ["new", "middle"]
'''
    path.write_text(text + "\n", encoding="utf-8")


def create_satim_tests() -> None:
    path = ROOT / "tests/test_satim_engine_repeatability.py"
    if path.exists():
        raise RuntimeError(f"unexpected existing file: {path}")
    path.write_text('''from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from fr24 import satim_engine, satim_engine_core

ENGINES = (satim_engine, satim_engine_core)


def _write_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)


@pytest.mark.parametrize(
    "engine",
    ENGINES,
    ids=lambda engine: engine.__name__.rsplit(".", 1)[-1],
)
def test_zip_backed_runs_replace_previous_extraction(tmp_path, engine):
    archive = tmp_path / "input.zip"
    output = tmp_path / "run"
    _write_zip(
        archive,
        {
            "bundle/screenshots/first.txt": "first",
            "bundle/stale.txt": "stale",
        },
    )

    first_root = engine.prepare_input_root(archive, output)
    assert (first_root / "screenshots" / "first.txt").read_text() == "first"
    assert (first_root / "stale.txt").exists()

    _write_zip(archive, {"bundle/screenshots/second.txt": "second"})
    second_root = engine.prepare_input_root(archive, output)

    assert second_root == first_root
    assert (second_root / "screenshots" / "second.txt").read_text() == "second"
    assert not (second_root / "screenshots" / "first.txt").exists()
    assert not (second_root / "stale.txt").exists()


def test_satim_engine_mirror_extraction_parity(tmp_path):
    archive = tmp_path / "input.zip"
    _write_zip(
        archive,
        {
            "bundle/screenshots/frame.txt": "frame",
            "bundle/annotations.json": "{}",
        },
    )

    snapshots = []
    returned_roots = []
    for engine in ENGINES:
        output = tmp_path / engine.__name__.rsplit(".", 1)[-1]
        root = engine.prepare_input_root(archive, output)
        returned_roots.append(root.relative_to(output).as_posix())
        snapshots.append(
            {
                item.relative_to(root).as_posix(): item.read_bytes()
                for item in sorted(root.rglob("*"))
                if item.is_file()
            }
        )

    assert returned_roots == ["_input_unpacked/bundle"] * 2
    assert snapshots[0] == snapshots[1]
''', encoding="utf-8")


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> None:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    print(f"Applying P2 remediation at {head}")

    for path in ("fr24/satim_engine.py", "fr24/satim_engine_core.py"):
        replace_once(
            path,
            "    safe_extract_zip(source, target)\n",
            "    safe_extract_zip(source, target, replace=True)\n",
        )

    replace_once(
        "server/backend/main.py",
        '''def sort_rows(rows, sort):
    if not sort:
        return rows
    reverse = sort.startswith("-")
    key = sort.lstrip("-")
    return sorted(rows, key=lambda row: _sort_value(row.get(key)), reverse=reverse)
''',
        '''def sort_rows(rows, sort):
    if not sort:
        return rows
    reverse = sort.startswith("-")
    key = sort.lstrip("-")
    present = [row for row in rows if row.get(key) not in (None, "")]
    missing = [row for row in rows if row.get(key) in (None, "")]
    return sorted(
        present,
        key=lambda row: _sort_value(row.get(key)),
        reverse=reverse,
    ) + missing
''',
    )
    append_backend_tests()
    create_satim_tests()

    emitter = ROOT / "tests/test_phase0_p2_patch_emitter.py"
    if not emitter.exists():
        raise RuntimeError("temporary emitter is missing")
    emitter.unlink()

    workflow = subprocess.check_output(
        ["git", "show", f"{RESTORE_WORKFLOW_FROM}:.github/workflows/backend-core.yml"],
        cwd=ROOT,
        text=True,
    )
    (ROOT / ".github/workflows/backend-core.yml").write_text(workflow, encoding="utf-8")

    script = ROOT / "scripts/apply_phase0_p2_remediation.py"
    script.unlink()

    run("ruff", "check", "fr24/satim_engine.py", "fr24/satim_engine_core.py", "server/backend/main.py", "tests/test_backend_api_security.py", "tests/test_satim_engine_repeatability.py")
    run("pytest", "-q", "tests/test_backend_api_security.py", "tests/test_satim_engine_repeatability.py")
    run("git", "diff", "--check")
    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    run("git", "add", "-A")
    run("git", "commit", "-m", "Remediate repeatable SATIM extraction and null-last sorting")
    run("git", "push", "origin", f"HEAD:{BRANCH}")


if __name__ == "__main__":
    main()
