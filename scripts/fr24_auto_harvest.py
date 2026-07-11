#!/usr/bin/env python3
"""
Automated FR24 harvest runner.

Safe behavior:
- Uses fr24_harvest.py as quota/queue source of truth.
- Processes one tail page at a time.
- Injects fr24_batch_click.js.
- Waits for native CSV/KML downloads.
- Runs commit-batch before navigating to the next tail.
- Stops when quota is exhausted, no targets remain, or a commit fails.

Does NOT bypass FR24 quota or login.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import subprocess
import sys
import time
from typing import Any

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


REPO = pathlib.Path(__file__).resolve().parents[1]
HARVEST = REPO / "scripts" / "fr24_harvest.py"
BATCH_JS = REPO / "scripts" / "fr24_batch_click.js"
DOWNLOADS = pathlib.Path(os.path.expanduser("~/Downloads"))
PROFILE = REPO / ".fr24_playwright_profile"


def run_controller(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(HARVEST), *args]
    return subprocess.run(cmd, cwd=str(REPO), text=True, capture_output=True, check=check)


def get_plan(count: int, no_kml: bool) -> dict[str, Any]:
    args = ["plan", "--count", str(count)]
    if no_kml:
        args.append("--no-kml")

    proc = run_controller(*args)
    return json.loads(proc.stdout)


def status_text() -> str:
    return run_controller("status").stdout


async def wait_for_download_files(flight_ids: list[str], no_kml: bool, timeout_s: int = 60) -> None:
    expected_exts = ["csv"] if no_kml else ["csv", "kml"]
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        missing = []

        for fid in flight_ids:
            for ext in expected_exts:
                matches = list(DOWNLOADS.glob(f"*{fid}*.{ext}"))
                partials = list(DOWNLOADS.glob(f"*{fid}*.{ext}.crdownload"))
                if not matches or partials:
                    missing.append(f"{fid}.{ext}")

        if not missing:
            return

        await asyncio.sleep(1)

    raise TimeoutError(f"Timed out waiting for downloads: {missing}")


async def run_one_tail(page, tail_group: dict[str, Any], pace_ms: int, no_kml: bool) -> bool:
    tail = tail_group["tail"]
    flight_ids = tail_group["flight_ids"]
    url = f"https://www.flightradar24.com/data/aircraft/{tail}"

    print(f"\n=== TAIL {tail} | {len(flight_ids)} flight(s) ===")
    print(f"Opening {url}")

    await page.goto(url, wait_until="domcontentloaded", timeout=60000)

    # Give FR24's Angular app time to render flight rows.
    await page.wait_for_timeout(5000)

    # Inject batch clicker.
    await page.add_script_tag(path=str(BATCH_JS))

    loaded = await page.evaluate("typeof window.fr24Batch")
    if loaded != "function":
        print(f"FAIL: fr24Batch not loaded on {tail}")
        return False

    print(f"Running fr24Batch for {tail}: {flight_ids}")

    result = await page.evaluate(
        """
        async ({ ids, paceMs, noKml }) => {
            return await window.fr24Batch(ids, { paceMs, noKml });
        }
        """,
        {"ids": flight_ids, "paceMs": pace_ms, "noKml": no_kml},
    )

    print(json.dumps(result, indent=2))

    if result.get("clicked", 0) == 0:
        print(f"NO CLICKS for {tail}; no quota should have been spent.")
        return False

    if result.get("missing"):
        print(f"WARNING: Missing rows for {tail}: {result['missing']}")

    print("Waiting for downloads...")
    await wait_for_download_files(flight_ids, no_kml=no_kml, timeout_s=90)

    print("Committing batch before navigation...")
    commit_args = ["commit-batch", *flight_ids]
    if no_kml:
        commit_args.append("--no-kml")

    proc = run_controller(*commit_args, check=False)
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)

    if proc.returncode != 0:
        print("STOP: commit-batch returned nonzero. Do not continue fetching.")
        return False

    return True


async def main_async(args: argparse.Namespace) -> int:
    if not HARVEST.exists():
        print(f"Missing controller: {HARVEST}", file=sys.stderr)
        return 2

    if not BATCH_JS.exists():
        print(f"Missing JS driver: {BATCH_JS}", file=sys.stderr)
        return 2

    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    PROFILE.mkdir(parents=True, exist_ok=True)

    print("Initial controller status:")
    print(status_text())

    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            headless=False,
            accept_downloads=True,
            downloads_path=str(DOWNLOADS),
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()

        # Give user a chance to login on first run.
        if args.login_check:
            print("\nLogin check: opening FR24. If not signed in, sign in now.")
            await page.goto("https://www.flightradar24.com/data/aircraft/N999ZY", wait_until="domcontentloaded")
            input("Press Enter here after confirming you are signed in to FR24 Gold... ")

        total_saved_groups = 0

        while True:
            plan = get_plan(count=args.count, no_kml=args.no_kml)
            selected = int(plan.get("selected", 0))
            remaining_units = int(plan.get("remaining_units", 0))
            groups = plan.get("by_tail", [])

            print("\nPLAN:")
            print(json.dumps(plan, indent=2))

            if selected <= 0 or not groups:
                print("STOP: no selected targets or no quota budget.")
                break

            for group in groups:
                ok = await run_one_tail(
                    page=page,
                    tail_group=group,
                    pace_ms=args.pace_ms,
                    no_kml=args.no_kml,
                )

                print("\nController status after tail:")
                print(status_text())

                if not ok:
                    await browser.close()
                    return 1

                total_saved_groups += 1

                # Re-plan after each tail if requested; safest because commit changes queue/quota.
                if args.replan_each_tail:
                    break

            if not args.loop:
                break

            # If replan_each_tail is enabled, loop immediately after one tail.
            # Otherwise, after finishing all groups in current plan, loop once more.
            continue

        await browser.close()

    print(f"DONE: processed tail groups={total_saved_groups}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Automate FR24 safe harvest workflow.")
    ap.add_argument("--count", type=int, default=12, help="Requested plan count per cycle.")
    ap.add_argument("--pace-ms", type=int, default=1500, help="Delay between export clicks.")
    ap.add_argument("--no-kml", action="store_true", help="CSV-only mode; costs 1 quota unit per flight.")
    ap.add_argument("--loop", action="store_true", help="Keep planning until quota/queue stops.")
    ap.add_argument("--replan-each-tail", action="store_true", default=True, help="Re-plan after each tail.")
    ap.add_argument("--no-login-check", dest="login_check", action="store_false", help="Skip first-run login pause.")
    args = ap.parse_args()

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())

