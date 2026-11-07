#!/usr/bin/env python3
"""Operator-local certification CLI for the Skywatcher/PITIRRE implication sidecar."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from skywatcher.core.knowledge_operator_certification import (
    OperatorCertificationError,
    certify_operator_package,
    discover_binding_candidates,
    preflight,
    write_review_template,
)

REPO = Path(__file__).resolve().parents[1]
DEFAULT_RLSM = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
DEFAULT_MFL = REPO / "data" / "skywatcher.db"
DEFAULT_CORPUS = REPO / "data" / "FR24_baseline"
DEFAULT_GOLD = REPO / "data" / "rlsm" / "gold_sample_300.jsonl"
DEFAULT_OUT = REPO / "outputs" / "knowledge_operator_certification"


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--rlsm-db", type=Path, default=DEFAULT_RLSM)
    parser.add_argument("--mfl-db", type=Path, default=DEFAULT_MFL)
    parser.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--expected-git-sha", default=None)


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_pre = sub.add_parser("preflight", help="verify frozen local inputs without mutation")
    _common(p_pre)

    p_gen = sub.add_parser(
        "generate-bindings",
        help="write the bounded gold-300 screenshot-to-MFL candidate review template",
    )
    _common(p_gen)
    p_gen.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUT / "binding_review",
    )

    p_cert = sub.add_parser(
        "certify",
        help="run gold audit + reviewed binding gates + scratch-sidecar materialization",
    )
    _common(p_cert)
    p_cert.add_argument("--binding-review", type=Path, required=True)
    p_cert.add_argument("--output-dir", type=Path, default=DEFAULT_OUT / "run")

    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            result = preflight(
                repo_root=REPO,
                rlsm_db=args.rlsm_db,
                mfl_db=args.mfl_db,
                corpus_root=args.corpus_root,
                gold_path=args.gold,
                expected_git_sha=args.expected_git_sha,
            )
            _print(result)
            return 0 if result["status"] == "PASS" else 2

        if args.command == "generate-bindings":
            pre = preflight(
                repo_root=REPO,
                rlsm_db=args.rlsm_db,
                mfl_db=args.mfl_db,
                corpus_root=args.corpus_root,
                gold_path=args.gold,
                expected_git_sha=args.expected_git_sha,
            )
            if pre["status"] != "PASS":
                _print(pre)
                return 2
            candidates, manifest = discover_binding_candidates(
                args.rlsm_db,
                args.mfl_db,
                args.gold,
            )
            args.output_dir.mkdir(parents=True, exist_ok=True)
            review_path = args.output_dir / "binding_review.template.jsonl"
            manifest_path = args.output_dir / "binding_candidate_manifest.json"
            write_review_template(candidates, manifest, review_path, manifest_path)
            _print(
                {
                    "status": "PASS",
                    "review_template": str(review_path),
                    "candidate_manifest": str(manifest_path),
                    **manifest,
                }
            )
            return 0

        result = certify_operator_package(
            repo_root=REPO,
            rlsm_db=args.rlsm_db,
            mfl_db=args.mfl_db,
            corpus_root=args.corpus_root,
            gold_path=args.gold,
            review_path=args.binding_review,
            output_dir=args.output_dir,
            expected_git_sha=args.expected_git_sha,
        )
        _print(
            {
                "certification_status": result["certification_status"],
                "git_sha": result["git_sha"],
                "binding_review": result["binding_review"],
                "rlsm_audit": result["rlsm_audit"],
                "sidecar": result["sidecar"],
                "outputs": result["outputs"],
            }
        )
        if result["certification_status"] == "PASS":
            return 0
        if result["certification_status"] in {"BLOCKED", "UNRESOLVED"}:
            return 2
        return 1
    except (OperatorCertificationError, OSError, ValueError) as exc:
        _print({"certification_status": "FAIL", "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
