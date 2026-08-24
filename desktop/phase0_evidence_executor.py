"""Temporary docs-only executor for the synchronized Phase 0 evidence commit.

This module exists only on the disposable executor branch. It appends bounded,
idempotent certification addenda to the required evidence surfaces, commits them
once on the pinned Phase 0 branch, and pushes normally without force.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import traceback
from pathlib import Path

REPOSITORY = "https://github.com/jotaele44/skywatcher-pr.git"
TARGET_BRANCH = "agent/repository-hardening-phase-0"
EXECUTOR_BRANCH = "codex/phase0-evidence-executor"
EXPECTED_CODE_HEAD = "035bf9aff9ec4502ea9a79ecc3da74e33a634644"
MERGE_HEAD = "8dedfcdbdaed34ad6d960e51471c3bf6a957e353"
FEATURE_PARENT = "1bfaea7c37ff42d0614934b0553cf8aacad9bfcc"
MAIN_PARENT = "9cdf63d584bc58495c32a573dc0fc9ddad981ab8"
MERGE_TREE = "d498d3aa86992c59997fdbe5eb24355d76c41e91"
MARKER = "<!-- PHASE0_SYNC_CERTIFICATION_V2 -->"

WORKFLOWS = [
    ("Backend core", "30390641872"),
    ("Skywatcher CI", "30390639144"),
    ("CodeQL", "30390638197"),
    ("Secret scan", "30390641514"),
    ("pip-audit", "30390638250"),
    ("Federation template drift", "30390642042"),
    ("desktop-build", "30390638674"),
    ("SATIM Engine CI", "30390638299"),
    ("SATIM Route Findings CI", "30390638336"),
    ("SATIM Runtime Smoke Tests", "30390638471"),
    ("SATIM Phase 2 Contracts", "30390641903"),
]

CONFLICTS = [
    ".github/workflows/ci.yml",
    "pyproject.toml",
    "fr24/rlsm_unlabeled.py",
    "fr24/satim_engine.py",
    "fr24/satim_engine_core.py",
    "scripts/federation_export.py",
    "scripts/rlsm_geocode_unlabeled.py",
    "scripts/rlsm_ocr_retry_tails.py",
    "src/skywatcher/fpim/aircraft_profile.py",
    "tests/test_aircraft_intelligence.py",
    "tests/test_fr24_todays_batch.py",
    "tests/test_maintenance.py",
    "tools/satim_engine/src/satim_engine/inventory.py",
]


def _run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=check, text=True, capture_output=True)


def _copy_checkout_credentials(source_repo: Path, target_repo: Path) -> None:
    result = _run(
        "git",
        "config",
        "--local",
        "--get-regexp",
        r"^http\..*\.extraheader$",
        cwd=source_repo,
        check=False,
    )
    if result.returncode or not result.stdout.strip():
        raise RuntimeError("persisted GitHub checkout credential header is unavailable")
    for line in result.stdout.splitlines():
        key, value = line.split(None, 1)
        _run("git", "config", "--local", key, value, cwd=target_repo)


def _append(path: Path, section: str) -> None:
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        raise RuntimeError(f"synchronization addendum already exists: {path}")
    path.write_text(text.rstrip() + "\n\n" + section.strip() + "\n", encoding="utf-8")


def _workflow_table() -> str:
    rows = ["| Workflow family | Run | Conclusion |", "|---|---:|---|"]
    rows.extend(f"| {name} | `{run_id}` | success |" for name, run_id in WORKFLOWS)
    return "\n".join(rows)


def _readme_addendum() -> str:
    return f'''{MARKER}
## Current Phase 0 synchronization certification

The authoritative synchronized code head is `{EXPECTED_CODE_HEAD}`. It descends from true two-parent merge `{MERGE_HEAD}`, whose ordered parents are Phase 0 head `{FEATURE_PARENT}` and current `main@{MAIN_PARENT}`. The independently reconstructed and connector-verified merge tree is `{MERGE_TREE}`.

- Pull request #110 is open, draft, mergeable, unmerged, and zero commits behind current main.
- The pull-request diff remains **98 files**.
- Current-main frontend, branding, FOIA canary workflows, desktop packaging, and `tests/test_server_smoke.py` are preserved.
- Net differences relative to current main under `frontend/` and production `data/` are zero.
- Field-level aircraft provenance remains fail-closed; callsign prefixes and ordinary flight-history rows cannot promote identity.
- Role, mission, purpose, target, schedule, typical operating area, and operational cueing remain unresolved or absent.
- Core and standalone SATIM archive implementations retain matching validation, bounded extraction, replacement rollback, and frozen-default behavior.
- `requirements.lock` equals the authoritative normalized resolver output; exact TheHub references remain pinned at `f00f2da0e6abcc885a8133e5c8b7aeb9756f5df8`.
- All eleven workflow families succeeded on the synchronized code head. The exact run ledger is in `docs/PHASE_0_TEST_EVIDENCE.md`.

This certification does not authorize merge or a ready-for-review transition.'''


def _fpim_addendum() -> str:
    return f'''{MARKER}
## Current-main synchronization preservation

FPIM was one of the explicitly adjudicated overlap surfaces during synchronization with `main@{MAIN_PARENT}`. The synchronized implementation at `{EXPECTED_CODE_HEAD}` preserves the Phase 0 identity boundary:

- `country` remains `Unknown` unless complete country-field provenance activates it.
- Callsign prefixes remain compatibility constants only and are not consulted by active resolution.
- Ordinary database flight rows enrich only observed counts and first/last-seen timestamps.
- Active reports leave role unresolved, mission lists empty, and operational-pattern cueing absent.

The conflict resolutions for `src/skywatcher/fpim/aircraft_profile.py` and `tests/test_aircraft_intelligence.py` were retained in merge tree `{MERGE_TREE}`. Backend core, Skywatcher CI, CodeQL, and the remaining workflow families all succeeded on `{EXPECTED_CODE_HEAD}`.'''


def _test_addendum() -> str:
    return f'''{MARKER}
## Synchronized code-head certification

- Synchronized merge commit: `{MERGE_HEAD}`
- Ordered merge parents: `{FEATURE_PARENT}`, `{MAIN_PARENT}`
- Validated merge tree: `{MERGE_TREE}`
- Certified synchronized code head after resolver refresh: `{EXPECTED_CODE_HEAD}`
- Pull-request changed files: **98**
- Net frontend delta relative to current main: **0**
- Net production-data delta relative to current main: **0**
- Inline review threads: **8 resolved, 0 unresolved**

The initial synchronized Skywatcher CI run generated artifact `8700628078` (`resolved-lock-6385acd961cda43e64fae7b2ab4bc1fb67883b3c`) and failed only the byte-for-byte lock comparison. The uploaded authoritative resolver output changed `annotated-doc` from `0.0.4` to `0.0.5` and `fastapi` from `0.140.7` to `0.140.13`; all other entries, exact TheHub SHAs, and no-editable-path constraints were unchanged. That output was committed verbatim as `requirements.lock` in `{EXPECTED_CODE_HEAD}`.

{_workflow_table()}

All eleven families concluded successfully on `{EXPECTED_CODE_HEAD}`. This documentation-only successor does not modify executable code and is identified as the evidence head in pull request #110.'''


def _migration_addendum() -> str:
    conflict_rows = "\n".join(f"- `{path}`" for path in CONFLICTS)
    return f'''{MARKER}
## Current-main synchronization record

Phase 0 was synchronized through true two-parent merge `{MERGE_HEAD}` with current `main@{MAIN_PARENT}`. The independently reconstructed terminal tree `{MERGE_TREE}` matched the connector-created tree byte-for-byte. The final code head `{EXPECTED_CODE_HEAD}` is zero commits behind main and retains 98 net changed files.

The overlap audit covered these 13 paths:

{conflict_rows}

Adjudication preserved current-main frontend, branding, FOIA canaries, desktop packaging, and server-smoke coverage while retaining Phase 0 CI, packaging, FPIM provenance, regression tests, and archive-security contracts. Ruff modernization was applied without changing public analytical schemas. The resolver-equivalent lock was refreshed from the CI-produced authoritative artifact.'''


def _remediation_addendum() -> str:
    return f'''{MARKER}
## Current-main overlap adjudication v2

- Synchronized merge head: `{MERGE_HEAD}`
- Phase 0 parent: `{FEATURE_PARENT}`
- Current-main parent: `{MAIN_PARENT}`
- Validated merge tree: `{MERGE_TREE}`
- Final synchronized code head: `{EXPECTED_CODE_HEAD}`
- Pull-request disposition: open, draft, mergeable, unmerged
- Branch state: `behind_by=0`
- Changed files: **98**
- Net frontend and production-data deltas relative to main: **0 / 0**

The 13-path overlap was adjudicated explicitly. Phase 0 security controls were retained on the conflicted CI, packaging, FPIM, FR24/SATIM, and test surfaces; current-main frontend, branding, FOIA canaries, desktop packaging, and later server-smoke coverage were inherited unchanged. Archive default parity was closed with the same frozen `DEFAULT_ARCHIVE_LIMITS` behavior in core and standalone SATIM implementations.

The first synchronized workflow pass correctly exposed resolver drift. Artifact `8700628078` was committed verbatim, producing `{EXPECTED_CODE_HEAD}`. All eleven workflow families then succeeded with the run IDs recorded in `docs/PHASE_0_TEST_EVIDENCE.md`.'''


def _closure_addendum() -> str:
    return f'''{MARKER}
## Final synchronized closure candidate

The synchronized code head `{EXPECTED_CODE_HEAD}` satisfies the closure framework:

1. `main@{MAIN_PARENT}` is an ancestor and `behind_by=0`.
2. PR #110 is open, draft, mergeable, and unmerged.
3. The PR retains 98 changed files with zero net frontend or production-data delta relative to main.
4. All eleven workflow families succeeded on the code head.
5. Resolver-equivalent locking passed after committing the authoritative generated lock.
6. Field-level provenance, country-prefix isolation, database-identity isolation, no-intent, and no-cueing regressions remain active.
7. Core and standalone SATIM archive validation and rollback behavior remain in parity.
8. All eight inline review threads are resolved; none are unresolved.

The evidence successor containing this addendum is documentation-only. Its exact SHA and applicable workflow conclusions are recorded in pull request #110. This report still does not authorize merge or a ready-for-review transition.'''


ADDENDA = {
    "README.md": _readme_addendum(),
    "docs/MODULE_SPEC_FPIM.md": _fpim_addendum(),
    "docs/PHASE_0_TEST_EVIDENCE.md": _test_addendum(),
    "docs/PHASE_0_MIGRATION_MAP.md": _migration_addendum(),
    "docs/PHASE_0_REMEDIATION_LEDGER.md": _remediation_addendum(),
    "docs/PHASE_0_REVIEW_CLOSURE.md": _closure_addendum(),
}


def execute_evidence_update(repo_root: Path) -> Path:
    receipt_path = repo_root / "phase0_evidence_update_receipt.json"
    try:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            subprocess.run(["git", "clone", "--no-checkout", REPOSITORY, str(repo)], check=True)
            _run("git", "checkout", "--detach", EXPECTED_CODE_HEAD, cwd=repo)
            remote_head = _run(
                "git", "ls-remote", "origin", f"refs/heads/{TARGET_BRANCH}", cwd=repo
            ).stdout.split()[0]
            if remote_head != EXPECTED_CODE_HEAD:
                raise RuntimeError(
                    f"feature branch moved before evidence update: {remote_head} != {EXPECTED_CODE_HEAD}"
                )

            for relative, section in ADDENDA.items():
                _append(repo / relative, section)

            _run("git", "config", "user.name", "phase0-evidence-bot", cwd=repo)
            _run(
                "git",
                "config",
                "user.email",
                "actions@users.noreply.github.com",
                cwd=repo,
            )
            _run("git", "add", *ADDENDA.keys(), cwd=repo)
            changed = _run("git", "diff", "--cached", "--name-only", cwd=repo).stdout.splitlines()
            if changed != sorted(ADDENDA):
                raise RuntimeError(f"unexpected evidence path set: {changed!r}")
            diff_check = _run("git", "diff", "--cached", "--check", cwd=repo, check=False)
            if diff_check.returncode:
                raise RuntimeError(diff_check.stdout + diff_check.stderr)
            _run(
                "git",
                "commit",
                "-m",
                "Record synchronized Phase 0 certification evidence",
                cwd=repo,
            )
            evidence_head = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
            _copy_checkout_credentials(repo_root, repo)
            push = _run(
                "git",
                "push",
                "origin",
                f"HEAD:refs/heads/{TARGET_BRANCH}",
                cwd=repo,
                check=False,
            )
            if push.returncode:
                raise RuntimeError("evidence push failed:\n" + push.stdout + "\n" + push.stderr)
            remote_after = _run(
                "git", "ls-remote", "origin", f"refs/heads/{TARGET_BRANCH}", cwd=repo
            ).stdout.split()[0]
            if remote_after != evidence_head:
                raise RuntimeError(f"evidence remote mismatch: {remote_after} != {evidence_head}")

            receipt = {
                "code_head": EXPECTED_CODE_HEAD,
                "evidence_head": evidence_head,
                "main_parent": MAIN_PARENT,
                "merge_head": MERGE_HEAD,
                "merge_tree": MERGE_TREE,
                "updated_paths": sorted(ADDENDA),
                "push_force": False,
                "remote_head": remote_after,
            }
    except Exception:
        receipt = {"error": traceback.format_exc(), "code_head": EXPECTED_CODE_HEAD}

    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt_path
