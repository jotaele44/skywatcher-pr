#!/usr/bin/env python3
"""Build a fail-closed Open MCT v4.1.0 dependency certification package.

This operator is intentionally external to the Skywatcher runtime. It downloads
and builds the exact upstream tag in an isolated work directory, records all
commands and hashes, generates security/licensing evidence, and emits one ZIP
for later ingestion. It NEVER changes dependency admission status.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TAG = "v4.1.0"
UPSTREAM = "https://github.com/nasa/openmct.git"
ARCHIVE_URL = "https://codeload.github.com/nasa/openmct/tar.gz/refs/tags/v4.1.0"
EXPECTED_SKYWATCHER_HEAD = "7400a4ec0551617bdbfa966ca1907954ccb14b4b"
PACKAGE_NAME = "openmct_v4_1_0_dependency_receipt"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    allow_failure: bool = False,
) -> dict[str, Any]:
    started = utc_now()
    before = time.monotonic()
    proc = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    receipt = {
        "command": command,
        "cwd": str(cwd) if cwd else None,
        "started_at_utc": started,
        "ended_at_utc": utc_now(),
        "duration_seconds": round(time.monotonic() - before, 3),
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    if proc.returncode != 0 and not allow_failure:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(command)}\n{proc.stderr}"
        )
    return receipt


def require_tool(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"required tool not found: {name}")
    return resolved


def parse_node_major(version_text: str) -> int:
    match = re.search(r"v?(\d+)", version_text)
    if not match:
        raise RuntimeError(f"unable to parse Node version: {version_text!r}")
    return int(match.group(1))


def file_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def copy_if_present(source: Path, destination_root: Path) -> list[str]:
    copied: list[str] = []
    if source.is_file():
        target = destination_root / source.name
        shutil.copy2(source, target)
        copied.append(target.name)
    return copied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Skywatcher PR #168 worktree (default: current directory)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output parent directory (default: <repo>/outputs)",
    )
    parser.add_argument(
        "--keep-work",
        action="store_true",
        help="Keep the extracted upstream build directory",
    )
    args = parser.parse_args()

    repo = args.repo.expanduser().resolve()
    output_parent = (args.output_dir or repo / "outputs").expanduser().resolve()
    output_parent.mkdir(parents=True, exist_ok=True)
    receipt_root = output_parent / PACKAGE_NAME
    if receipt_root.exists():
        shutil.rmtree(receipt_root)
    receipt_root.mkdir(parents=True)

    command_receipts: list[dict[str, Any]] = []
    blockers: list[str] = []
    warnings: list[str] = []

    try:
        for tool in ("git", "node", "npm"):
            require_tool(tool)

        head = run(["git", "rev-parse", "HEAD"], cwd=repo)
        command_receipts.append(head)
        actual_head = head["stdout"].strip()
        status = run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=repo)
        command_receipts.append(status)
        if actual_head != EXPECTED_SKYWATCHER_HEAD:
            blockers.append(
                f"Skywatcher HEAD mismatch: expected {EXPECTED_SKYWATCHER_HEAD}, got {actual_head}"
            )
        if status["stdout"].strip():
            blockers.append("Skywatcher worktree is not clean")

        tag_refs = run(
            [
                "git",
                "ls-remote",
                "--tags",
                UPSTREAM,
                f"refs/tags/{TAG}",
                f"refs/tags/{TAG}^{{}}",
            ]
        )
        command_receipts.append(tag_refs)
        refs = {}
        for line in tag_refs["stdout"].splitlines():
            sha, ref = line.split("\t", 1)
            refs[ref] = sha
        direct_ref = refs.get(f"refs/tags/{TAG}")
        peeled_ref = refs.get(f"refs/tags/{TAG}^{{}}")
        if not direct_ref:
            blockers.append(f"tag ref not found: {TAG}")
        tag_type = "annotated" if peeled_ref else "lightweight"
        exact_commit = peeled_ref or direct_ref

        node_version = run(["node", "--version"])
        npm_version = run(["npm", "--version"])
        command_receipts.extend([node_version, npm_version])
        node_major = parse_node_major(node_version["stdout"].strip())
        if node_major < 18 or node_major >= 23:
            blockers.append(
                f"Node {node_version['stdout'].strip()} is outside Open MCT range >=18.14.2 <23"
            )
        elif node_major == 18:
            version_parts = re.findall(r"\d+", node_version["stdout"])
            if len(version_parts) >= 3 and (int(version_parts[1]), int(version_parts[2])) < (14, 2):
                blockers.append("Node 18 version is below 18.14.2")

        archive = receipt_root / "openmct-v4.1.0.tar.gz"
        request = urllib.request.Request(
            ARCHIVE_URL,
            headers={"User-Agent": "skywatcher-openmct-certifier/1.0"},
        )
        with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as out:
            final_url = response.geturl()
            shutil.copyfileobj(response, out)
        archive_sha = sha256_file(archive)
        archive_size = archive.stat().st_size

        work_parent = Path(tempfile.mkdtemp(prefix="openmct-v4.1.0-"))
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            unsafe = [
                member.name
                for member in members
                if member.name.startswith("/") or ".." in Path(member.name).parts
            ]
            if unsafe:
                raise RuntimeError(f"archive contains unsafe paths: {unsafe[:5]}")
            tar.extractall(work_parent, filter="data")
        roots = sorted(p for p in work_parent.iterdir() if p.is_dir())
        if len(roots) != 1:
            raise RuntimeError(f"expected one extracted root, found {len(roots)}")
        source_root = roots[0]

        package_json = json.loads((source_root / "package.json").read_text(encoding="utf-8"))
        if package_json.get("version") != "4.1.0":
            blockers.append(f"package version mismatch: {package_json.get('version')!r}")
        if package_json.get("license") != "Apache-2.0":
            blockers.append(f"package license mismatch: {package_json.get('license')!r}")

        source_evidence = receipt_root / "source_evidence"
        source_evidence.mkdir()
        evidence_names = ["package.json", "package-lock.json", ".nvmrc", "LICENSE.md", "SECURITY.md"]
        copied_evidence: list[str] = []
        for name in evidence_names:
            copied_evidence.extend(copy_if_present(source_root / name, source_evidence))
        for path in sorted(source_root.iterdir()):
            upper = path.name.upper()
            if path.is_file() and ("NOTICE" in upper or "LICENSE" in upper or "COPYRIGHT" in upper):
                if path.name not in copied_evidence:
                    copied_evidence.extend(copy_if_present(path, source_evidence))
        if not (source_root / "package-lock.json").exists():
            blockers.append("package-lock.json is missing")

        env = os.environ.copy()
        env["CI"] = "true"
        env["npm_config_audit"] = "false"
        env["npm_config_fund"] = "false"
        install = run(["npm", "ci"], cwd=source_root, env=env)
        command_receipts.append(install)
        build = run(["npm", "run", "build:prod"], cwd=source_root, env=env)
        command_receipts.append(build)

        dist = source_root / "dist"
        if not dist.is_dir():
            blockers.append("production build did not create dist/")
        dist_manifest = file_manifest(dist) if dist.is_dir() else []

        audit_path = receipt_root / "audit.json"
        audit = run(["npm", "audit", "--json"], cwd=source_root, allow_failure=True)
        command_receipts.append(audit)
        audit_path.write_text(audit["stdout"] or "{}\n", encoding="utf-8")
        try:
            audit_json = json.loads(audit["stdout"] or "{}")
            vulnerabilities = audit_json.get("metadata", {}).get("vulnerabilities", {})
            if vulnerabilities.get("critical", 0) or vulnerabilities.get("high", 0):
                blockers.append(
                    "npm audit reports high/critical vulnerabilities; human adjudication required"
                )
        except json.JSONDecodeError:
            blockers.append("npm audit did not return valid JSON")

        sbom_path = receipt_root / "sbom.cdx.json"
        sbom = run(
            [
                "npm",
                "exec",
                "--yes",
                "--package=@cyclonedx/cyclonedx-npm",
                "--",
                "cyclonedx-npm",
                "--output-file",
                str(sbom_path),
                "--output-format",
                "JSON",
            ],
            cwd=source_root,
            env=env,
        )
        command_receipts.append(sbom)
        if not sbom_path.is_file():
            blockers.append("CycloneDX SBOM was not generated")

        license_path = receipt_root / "license-report.json"
        licenses = run(
            [
                "npm",
                "exec",
                "--yes",
                "--package=license-checker",
                "--",
                "license-checker",
                "--json",
                "--production",
            ],
            cwd=source_root,
            env=env,
        )
        command_receipts.append(licenses)
        license_path.write_text(licenses["stdout"], encoding="utf-8")
        try:
            json.loads(licenses["stdout"])
        except json.JSONDecodeError:
            blockers.append("license report is not valid JSON")

        url_pattern = re.compile(rb"(?:https?|wss?)://[^\s\"'<>]+", re.IGNORECASE)
        external_rows: list[dict[str, Any]] = []
        if dist.is_dir():
            for path in sorted(p for p in dist.rglob("*") if p.is_file()):
                data = path.read_bytes()
                urls = sorted({m.decode("utf-8", "replace") for m in url_pattern.findall(data)})
                if urls:
                    external_rows.append(
                        {"path": path.relative_to(dist).as_posix(), "urls": urls}
                    )
        canonical_json(receipt_root / "external-reference-scan.json", external_rows)
        if external_rows:
            warnings.append(
                "Built assets contain URL-like strings; inspect external-reference-scan.json before admission"
            )

        minimum_dist = receipt_root / "minimum_dist"
        minimum_dist.mkdir()
        if dist.is_dir():
            shutil.copytree(dist, minimum_dist / "dist")
        if (source_root / "LICENSE.md").is_file():
            shutil.copy2(source_root / "LICENSE.md", minimum_dist / "LICENSE.md")

        canonical_json(receipt_root / "source-manifest.json", file_manifest(source_evidence))
        canonical_json(receipt_root / "dist-manifest.json", dist_manifest)
        canonical_json(
            receipt_root / "release.json",
            {
                "schema": "skywatcher.openmct-release-receipt.v1",
                "generated_at_utc": utc_now(),
                "upstream": UPSTREAM,
                "tag": TAG,
                "tag_type": tag_type,
                "tag_ref_sha": direct_ref,
                "exact_commit_sha": exact_commit,
                "archive_url_requested": ARCHIVE_URL,
                "archive_url_final": final_url,
                "archive_bytes": archive_size,
                "archive_sha256": archive_sha,
                "archive_member_count": len(members),
                "archive_top_level": source_root.name,
                "package_version": package_json.get("version"),
                "package_license": package_json.get("license"),
                "node_engine": package_json.get("engines", {}).get("node"),
                "browserslist": package_json.get("browserslist"),
                "admission_status": "candidate_only",
            },
        )
        (receipt_root / "ARCHIVE_SHA256.txt").write_text(
            f"{archive_sha}  openmct-v4.1.0.tar.gz\n", encoding="utf-8"
        )
        canonical_json(
            receipt_root / "build-receipt.json",
            {
                "schema": "skywatcher.openmct-build-receipt.v1",
                "generated_at_utc": utc_now(),
                "host": {
                    "platform": platform.platform(),
                    "python": sys.version,
                    "node": node_version["stdout"].strip(),
                    "npm": npm_version["stdout"].strip(),
                },
                "skywatcher_repo": str(repo),
                "skywatcher_head": actual_head,
                "skywatcher_clean": not bool(status["stdout"].strip()),
                "commands": command_receipts,
                "blockers": blockers,
                "warnings": warnings,
                "admission_status": "blocked" if blockers else "candidate_for_human_adjudication",
            },
        )

        package_manifest = file_manifest(receipt_root)
        canonical_json(receipt_root / "PACKAGE_MANIFEST.json", package_manifest)
        package_digest = hashlib.sha256(
            json.dumps(package_manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        (receipt_root / "PACKAGE_SHA256.txt").write_text(package_digest + "\n", encoding="utf-8")

        zip_path = output_parent / f"{PACKAGE_NAME}.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(p for p in receipt_root.rglob("*") if p.is_file()):
                zf.write(path, Path(PACKAGE_NAME) / path.relative_to(receipt_root))

        final = {
            "package": str(zip_path),
            "package_bytes": zip_path.stat().st_size,
            "package_sha256": sha256_file(zip_path),
            "receipt_root": str(receipt_root),
            "blockers": blockers,
            "warnings": warnings,
            "admission_status": "blocked" if blockers else "candidate_for_human_adjudication",
        }
        print(json.dumps(final, indent=2))

        if not args.keep_work:
            shutil.rmtree(work_parent, ignore_errors=True)
        else:
            print(f"kept upstream work directory: {work_parent}", file=sys.stderr)

        return 2 if blockers else 0

    except Exception as exc:
        blockers.append(f"operator failure: {type(exc).__name__}: {exc}")
        canonical_json(
            receipt_root / "build-receipt.json",
            {
                "schema": "skywatcher.openmct-build-receipt.v1",
                "generated_at_utc": utc_now(),
                "commands": command_receipts,
                "blockers": blockers,
                "warnings": warnings,
                "admission_status": "blocked",
            },
        )
        print(blockers[-1], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
