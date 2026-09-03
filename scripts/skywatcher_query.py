#!/usr/bin/env python3
"""
Skywatcher query CLI — ask questions about the FR24 flight data.

Answers are grounded on the committed per-craft profiles (build them first with
``scripts/build_craft_profiles.py``). By default a natural-language answer is
produced via the Anthropic wrapper when ``ANTHROPIC_API_KEY`` is set; otherwise
(and with ``--deterministic``) the deterministic engine answers directly. Either
way the facts come only from the profiles — no intent/mission is inferred.

Examples:
    python3 scripts/skywatcher_query.py "regular schedule and home base for N5854Z"
    python3 scripts/skywatcher_query.py --deterministic "what LZs does N767PD prefer?"
    python3 scripts/skywatcher_query.py --craft N5854Z
    python3 scripts/skywatcher_query.py --json "what recurring routes are new?"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from skywatcher.query.engine import QueryEngine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", nargs="?", default=None, help="Natural-language question")
    ap.add_argument("--craft", default=None, help="Dump a full profile for this registration")
    ap.add_argument("--deterministic", action="store_true",
                    help="Force the deterministic engine (no LLM)")
    ap.add_argument("--json", action="store_true", help="Emit the structured Answer as JSON")
    ap.add_argument("--db", default=None, help="craft_profiles SQLite path (else JSON dir)")
    ap.add_argument("--profile-dir", default=None, help="profiles/craft JSON directory")
    args = ap.parse_args()

    prompt = args.prompt
    if args.craft and not prompt:
        prompt = args.craft  # engine resolves the registration slot
    if not prompt:
        ap.error("provide a prompt or --craft")

    db_path = Path(args.db) if args.db else None
    profile_dir = Path(args.profile_dir) if args.profile_dir else None
    engine = QueryEngine(db_path=db_path,
                         profile_dir=profile_dir or QueryEngine().profile_dir)

    if not engine.profiles():
        print("[skywatcher_query] no profiles found. Run scripts/build_craft_profiles.py first.")
        return 0

    answer = engine.answer(prompt)

    if args.json:
        print(json.dumps(answer.to_dict(), indent=2, ensure_ascii=False))
        return 0

    if args.deterministic:
        print(answer.to_text())
        return 0

    # Natural-language phrasing (degrades to deterministic text without a key).
    from skywatcher.query.llm import ask
    print(ask(prompt, engine=engine))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
