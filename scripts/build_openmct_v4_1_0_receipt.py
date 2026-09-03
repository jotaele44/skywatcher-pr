#!/usr/bin/env python3
"""Build a fail-closed Open MCT v4.1.0 dependency certification package."""

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
DROP_DIST_PREFIXES = ("darkmatterTheme.",)
URL_RE = re.compile(rb"(?:https?|wss?)://[^\s\"'<>]+", re.IGNORECASE)
RUNTIME_URL_RE = re.compile(
    rb"(?:@import\s+url\(|url\(|fetch\(|new\s+WebSocket\(|XMLHttpRequest).*?"
    rb"(?:https?|wss?)://[^\s\"'<>]+",
    re.IGNORECASE | re.DOTALL,
)
SEVERITIES = {"high", "critical"}


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
        capture_output=True,
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


def file_manifest(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(p for p in root.rglob("*") if p.is_file())
    ]


def copy_if_present(source: Path, destination_root: Path) -> list[str]:
    if not source.is_file():
        return []
    target = destination_root / source.name
    shutil.copy2(source, target)
    return [target.name]


def parse_node_version(text: str) -> tuple[int, int, int]:
    parts = [int(value) for value in re.findall(r"\d+", text)[:3]]
    if len(parts) != 3:
        raise RuntimeError(f"unable to parse Node version: {text!r}")
    return parts[0], parts[1], parts[2]


def sourcemap_packages(dist: Path) -> set[str]:
    packages: set[str] = set()
    for path in dist.rglob("*.map"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        for source in payload.get("sources", []):
            marker = "node_modules/"
            if marker not in source:
                continue
            tail = source.split(marker, 1)[1]
            pieces = tail.split("/")
            package = "/".join(pieces[:2]) if tail.startswith("@") else pieces[0]
            packages.add(package)
    return packages


def classify_audit(
    audit_json: dict[str, Any],
    package_lock: dict[str, Any],
    shipped_packages: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    lock_packages = package_lock.get("packages", {})
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    for name, finding in sorted(audit_json.get("vulnerabilities", {}).items()):
        severity = finding.get("severity")
        if severity not in SEVERITIES:
            continue
        lock_entry = lock_packages.get(f"node_modules/{name}", {})
        dev_only = bool(lock_entry.get("dev", False))
        shipped = name in shipped_packages
        adjudication = (
            "build_only_nonshipped"
            if dev_only and not shipped
            else "unadjudicated_shipped_or_unproven"
        )
        row = {
            "package": name,
            "severity": severity,
            "direct": bool(finding.get("isDirect", False)),
            "dev_only": dev_only,
            "present_in_dist_sourcemaps": shipped,
            "via": finding.get("via"),
            "range": finding.get("range"),
            "nodes": finding.get("nodes"),
            "fix_available": finding.get("fixAvailable"),
            "adjudication": adjudication,
        }
        rows.append(row)
        if adjudication != "build_only_nonshipped":
            blockers.append(f"{severity} finding remains unadjudicated: {name}")
    return rows, blockers


def reduced_distribution(dist: Path, destination: Path) -> list[str]:
    removed: list[str] = []
    destination.mkdir(parents=True)
    for path in sorted(p for p in dist.rglob("*") if p.is_file()):
        relative = path.relative_to(dist)
        if relative.name.startswith(DROP_DIST_PREFIXES):
            removed.append(relative.as_posix())
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return removed


def scan_external_references(
    root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_rows: list[dict[str, Any]] = []
    runtime_rows: list[dict[str, Any]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        data = path.read_bytes()
        urls = sorted({m.decode("utf-8", "replace") for m in URL_RE.findall(data)})
        runtime = sorted(
            {m.decode("utf-8", "replace") for m in RUNTIME_URL_RE.findall(data)}
        )
        relative = path.relative_to(root).as_posix()
        if urls:
            all_rows.append({"path": relative, "urls": urls})
        if runtime:
            runtime_rows.append({"path": relative, "matches": runtime})
    return all_rows, runtime_rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--keep-work", action="store_true")
    args = parser.parse_args()

    repo = args.repo.expanduser().resolve()
    output_parent = (args.output_dir or repo / "outputs").expanduser().resolve()
    receipt_root = output_parent / PACKAGE_NAME
    if receipt_root.exists():
        shutil.rmtree(receipt_root)
    receipt_root.mkdir(parents=True, exist_ok=True)

    commands: list[dict[str, Any]] = []
    blockers: list[str] = []
    warnings: list[str] = []
    work_parent: Path | None = None

    try:
        for tool in ("git", "node", "npm"):
            if not shutil.which(tool):
                raise RuntimeError(f"required tool not found: {tool}")

        head = run(["git", "rev-parse", "HEAD"], cwd=repo)
        status = run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=repo
        )
        commands.extend([head, status])
        actual_head = head["stdout"].strip()
        if actual_head != EXPECTED_SKYWATCHER_HEAD:
            blockers.append(
                f"Skywatcher HEAD mismatch: expected {EXPECTED_SKYWATCHER_HEAD}, "
                f"got {actual_head}"
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
        commands.append(tag_refs)
        refs = {
            ref: sha
            for sha, ref in (
                line.split("\t", 1) for line in tag_refs["stdout"].splitlines()
            )
        }
        direct_ref = refs.get(f"refs/tags/{TAG}")
        peeled_ref = refs.get(f"refs/tags/{TAG}^{{}}")
        if not direct_ref:
            blockers.append(f"tag ref not found: {TAG}")
        tag_type = "annotated" if peeled_ref else "lightweight"
        exact_commit = peeled_ref or direct_ref

        node_version = run(["node", "--version"])
        npm_version = run(["npm", "--version"])
        commands.extend([node_version, npm_version])
        node_tuple = parse_node_version(node_version["stdout"])
        if node_tuple < (18, 14, 2) or node_tuple >= (23, 0, 0):
            blockers.append(
                f"Node {node_version['stdout'].strip()} is outside >=18.14.2 <23"
            )

        archive = receipt_root / "openmct-v4.1.0.tar.gz"
        request = urllib.request.Request(
            ARCHIVE_URL,
            headers={"User-Agent": "skywatcher-openmct-certifier/1.1"},
        )
        with urllib.request.urlopen(request, timeout=120) as response, archive.open(
            "wb"
        ) as out:
            final_url = response.geturl()
            shutil.copyfileobj(response, out)

        work_parent = Path(tempfile.mkdtemp(prefix="openmct-v4.1.0-"))
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            unsafe = [
                member.name
                for member in members
                if member.name.startswith("/") or ".." in Path(member.name).parts
            ]
            if unsafe:
                raise RuntimeError(f"unsafe archive paths: {unsafe[:5]}")
            tar.extractall(work_parent, filter="data")
        roots = [path for path in work_parent.iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise RuntimeError(f"expected one extracted root, found {len(roots)}")
        source_root = roots[0]

        package_json = json.loads(
            (source_root / "package.json").read_text(encoding="utf-8")
        )
        package_lock = json.loads(
            (source_root / "package-lock.json").read_text(encoding="utf-8")
        )
        if package_json.get("version") != "4.1.0":
            blockers.append("package version mismatch")
        if package_json.get("license") != "Apache-2.0":
            blockers.append("package license mismatch")

        source_evidence = receipt_root / "source_evidence"
        source_evidence.mkdir()
        copied: list[str] = []
        for name in (
            "package.json",
            "package-lock.json",
            ".nvmrc",
            "LICENSE.md",
            "SECURITY.md",
        ):
            copied.extend(copy_if_present(source_root / name, source_evidence))
        for path in sorted(source_root.iterdir()):
            upper = path.name.upper()
            if (
                path.is_file()
                and (
                    "NOTICE" in upper
                    or "LICENSE" in upper
                    or "COPYRIGHT" in upper
                )
                and path.name not in copied
            ):
                copied.extend(copy_if_present(path, source_evidence))

        env = os.environ.copy()
        env.update(
            {"CI": "true", "npm_config_audit": "false", "npm_config_fund": "false"}
        )
        install = run(["npm", "ci"], cwd=source_root, env=env)
        build = run(["npm", "run", "build:prod"], cwd=source_root, env=env)
        commands.extend([install, build])
        dist = source_root / "dist"
        if not dist.is_dir():
            raise RuntimeError("production build did not create dist/")

        audit = run(["npm", "audit", "--json"], cwd=source_root, allow_failure=True)
        commands.append(audit)
        (receipt_root / "audit.json").write_text(
            audit["stdout"] or "{}\n", encoding="utf-8"
        )
        audit_json = json.loads(audit["stdout"] or "{}")

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
        commands.append(sbom)

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
        commands.append(licenses)
        json.loads(licenses["stdout"])
        (receipt_root / "license-report.json").write_text(
            licenses["stdout"], encoding="utf-8"
        )

        shipped_packages = sourcemap_packages(dist)
        audit_rows, audit_blockers = classify_audit(
            audit_json, package_lock, shipped_packages
        )
        blockers.extend(audit_blockers)
        canonical_json(
            receipt_root / "security-adjudication.json",
            {
                "policy": (
                    "High/critical findings are adjudicated build-only only when "
                    "the lockfile marks the package dev-only and no built sourcemap "
                    "references that package."
                ),
                "shipped_packages": sorted(shipped_packages),
                "findings": audit_rows,
                "unadjudicated_count": len(audit_blockers),
            },
        )

        reduced_root = receipt_root / "minimum_dist" / "dist"
        removed = reduced_distribution(dist, reduced_root)
        if not removed:
            blockers.append("expected remote-font theme removal did not occur")
        shutil.copy2(
            source_root / "LICENSE.md", receipt_root / "minimum_dist" / "LICENSE.md"
        )

        all_urls, runtime_urls = scan_external_references(reduced_root)
        canonical_json(receipt_root / "external-reference-scan.json", all_urls)
        canonical_json(
            receipt_root / "runtime-external-origin-scan.json", runtime_urls
        )
        if runtime_urls:
            blockers.append("reduced distribution retains runtime external origins")

        canonical_json(
            receipt_root / "source-manifest.json", file_manifest(source_evidence)
        )
        canonical_json(receipt_root / "dist-manifest.json", file_manifest(dist))
        canonical_json(
            receipt_root / "reduced-dist-manifest.json", file_manifest(reduced_root)
        )
        canonical_json(
            receipt_root / "release.json",
            {
                "schema": "skywatcher.openmct-release-receipt.v2",
                "generated_at_utc": utc_now(),
                "upstream": UPSTREAM,
                "tag": TAG,
                "tag_type": tag_type,
                "tag_ref_sha": direct_ref,
                "exact_commit_sha": exact_commit,
                "archive_url_requested": ARCHIVE_URL,
                "archive_url_final": final_url,
                "archive_bytes": archive.stat().st_size,
                "archive_sha256": sha256_file(archive),
                "archive_member_count": len(members),
                "archive_top_level": source_root.name,
                "package_version": package_json.get("version"),
                "package_license": package_json.get("license"),
                "node_engine": package_json.get("engines", {}).get("node"),
                "browserslist": package_json.get("browserslist"),
                "removed_distribution_files": removed,
                "admission_status": "candidate_only",
            },
        )
        (receipt_root / "ARCHIVE_SHA256.txt").write_text(
            f"{sha256_file(archive)}  openmct-v4.1.0.tar.gz\n", encoding="utf-8"
        )
        canonical_json(
            receipt_root / "build-receipt.json",
            {
                "schema": "skywatcher.openmct-build-receipt.v2",
                "generated_at_utc": utc_now(),
                "host": {
                    "platform": platform.platform(),
                    "python": sys.version,
                    "node": node_version["stdout"].strip(),
                    "npm": npm_version["stdout"].strip(),
                },
                "skywatcher_head": actual_head,
                "skywatcher_clean": not bool(status["stdout"].strip()),
                "commands": commands,
                "blockers": blockers,
                "warnings": warnings,
                "admission_status": (
                    "blocked" if blockers else "candidate_for_human_adjudication"
                ),
            },
        )

        package_manifest = file_manifest(receipt_root)
        canonical_json(receipt_root / "PACKAGE_MANIFEST.json", package_manifest)
        package_digest = hashlib.sha256(
            json.dumps(
                package_manifest, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        (receipt_root / "PACKAGE_SHA256.txt").write_text(
            f"{package_digest}\n", encoding="utf-8"
        )

        zip_path = output_parent / f"{PACKAGE_NAME}.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive_zip:
            for path in sorted(p for p in receipt_root.rglob("*") if p.is_file()):
                archive_zip.write(path, path.relative_to(receipt_root).as_posix())

        print(f"package={zip_path}")
        print(f"package_sha256={sha256_file(zip_path)}")
        print(
            "admission_status="
            + ("blocked" if blockers else "candidate_for_human_adjudication")
        )
        print("blockers=" + json.dumps(blockers))
        return 2 if blockers else 0
    finally:
        if work_parent and work_parent.exists() and not args.keep_work:
            shutil.rmtree(work_parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
