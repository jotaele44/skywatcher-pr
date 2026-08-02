"""
RLSM single-command pipeline.

One entry point that runs the whole screenshot extraction chain in the right
order, resumably, with a preflight that fails fast and a report at the end.
Before this, data/rlsm/HANDOFF.md asked the operator to hand-run six module
invocations in a sequence they had to get right, with no preflight and no
summary of what actually came out.

Usage (from the repo root):

    ./run-rlsm.sh                      # everything, resumable
    ./run-rlsm.sh --status             # what is done, what is pending
    ./run-rlsm.sh --dry-run            # print the stage plan, touch nothing
    ./run-rlsm.sh --limit 200          # smoke test over 200 images
    ./run-rlsm.sh --stage pins         # re-run one stage
    ./run-rlsm.sh --from icons         # resume from a stage onward
    ./run-rlsm.sh --skip-icons         # OCR + pins + exports only

Every stage is idempotent and resumable: OCR only touches screenshots still
marked pending, extractors only touch screenshots with no derived rows yet, and
raw OCR is never overwritten. Ctrl-C and re-run is always safe.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
SCHEMA = REPO / "data" / "rlsm" / "schema.sql"
BASELINE = REPO / "data" / "FR24_baseline"
OUTPUTS = REPO / "outputs"
REPORT = OUTPUTS / "rlsm_run_report.md"

# Stage order. `blob` (the ~500k-candidate ground-feature pass) is deliberately
# not in the default set — see DEFAULT_STAGES.
ALL_STAGES = [
    "preflight", "inventory", "ocr", "aircraft", "pins", "icons",
    "geocode", "review", "export", "report",
]

# `unlabeled` is available as an explicit --stage but excluded by default: it
# emits ~40-50 candidates per image (~500k rows) using a satellite-imagery
# taxonomy (pad/tank/quarry) aimed at ground features rather than app chrome,
# and would swamp manual_review_queue. The icon channel is the better-typed
# signal for on-screen glyphs.
OPTIONAL_STAGES = ["unlabeled"]
DEFAULT_STAGES = list(ALL_STAGES)


class StageError(RuntimeError):
    pass


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    return conn


def _run_module(module: str, args: list[str], env_extra: dict | None = None) -> None:
    """Run a pipeline module as a subprocess so one stage cannot poison another."""
    env = dict(os.environ)
    env.setdefault("OMP_THREAD_LIMIT", "1")
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, "-m", module, *args]
    print(f"    $ {' '.join(cmd[2:])}", flush=True)
    proc = subprocess.run(cmd, cwd=str(REPO), env=env)
    if proc.returncode != 0:
        raise StageError(f"{module} exited {proc.returncode}")


def _run_script(script: Path, args: list[str]) -> None:
    cmd = [sys.executable, str(script), *args]
    print(f"    $ {script.name} {' '.join(args)}", flush=True)
    proc = subprocess.run(cmd, cwd=str(REPO), env=dict(os.environ))
    if proc.returncode != 0:
        raise StageError(f"{script.name} exited {proc.returncode}")


# --------------------------------------------------------------------------- #
# preflight
# --------------------------------------------------------------------------- #

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _count(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    try:
        row = conn.execute(sql, params).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def preflight(ctx: dict) -> dict:
    """Check every precondition before spending hours of OCR."""
    problems: list[str] = []
    warnings: list[str] = []
    info: dict = {}

    # Only the stages that decode images need the corpus and the OCR toolchain.
    # Everything downstream of the sqlite — pins, review, export, report — runs
    # off the DB alone, which is the operator-Mac / CI split described in
    # docs/SCREENSHOT_DATA_STRATEGY.md §6.
    needs_pixels = bool({"inventory", "ocr", "icons", "unlabeled"} & set(ctx["stages"]))
    info["needs_pixels"] = needs_pixels

    # 1) Corpus reachable.
    if needs_pixels:
        if not BASELINE.exists():
            problems.append(
                f"corpus directory missing: {BASELINE.relative_to(REPO)}\n"
                f"      If the corpus lives elsewhere, symlink it (paths in the DB\n"
                f"      are stored relative to the repo root, so this must be the\n"
                f"      location):\n"
                f"        ln -s ~/Documents/GitHub/spiderweb-pr/data/FR24_baseline "
                f"{BASELINE.relative_to(REPO)}")
        else:
            n_images = sum(1 for p in BASELINE.rglob("*")
                           if p.is_file() and p.suffix.lower() in
                           {".png", ".jpg", ".jpeg", ".heic", ".webp"})
            info["corpus_images_on_disk"] = n_images
            if n_images == 0:
                problems.append(
                    f"{BASELINE.relative_to(REPO)} exists but holds no images "
                    f"(.png/.jpg/.jpeg/.heic/.webp)")

    # 2) OCR toolchain.
    if needs_pixels:
        if shutil.which("tesseract") is None:
            problems.append("tesseract not on PATH — `brew install tesseract`")
        try:
            import PIL  # noqa: F401
        except ImportError:
            problems.append("Pillow not installed — `pip install -r requirements.txt`")
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            problems.append("pytesseract not installed — `pip install pytesseract`")
        try:
            import pillow_heif  # noqa: F401
        except ImportError:
            warnings.append("pillow-heif not installed — .heic screenshots will be "
                            "recorded as unreadable")

    # 3) Gazetteer present.
    gpkg = REPO / "data" / "reference" / "Gazetteer_PR_GNIS.gpkg"
    if not gpkg.exists():
        problems.append(f"missing gazetteer: {gpkg.relative_to(REPO)}")
    else:
        try:
            from fr24.rlsm_gazetteer import load_gazetteer
            info["gazetteer_keys"] = load_gazetteer().stats()["keys"]
        except Exception as exc:
            problems.append(f"gazetteer failed to load: {type(exc).__name__}: {exc}")

    # 4) DB + schema. Deliberately does not open the DB under --dry-run when the
    #    file is absent: sqlite3.connect() creates an empty file as a side effect,
    #    and a dry run must leave the working tree exactly as it found it.
    conn = None
    if not DB.exists() and ctx["dry_run"]:
        info["schema"] = "would be created"
    else:
        DB.parent.mkdir(parents=True, exist_ok=True)
        OUTPUTS.mkdir(parents=True, exist_ok=True)
        conn = _connect()
        if _table_exists(conn, "screenshots"):
            info["schema"] = "present"
        elif ctx["dry_run"]:
            info["schema"] = "would be created"
        else:
            conn.executescript(SCHEMA.read_text())
            conn.commit()
            info["schema"] = "created"
        # icon_observations post-dates the original schema; create it in place.
        if not ctx["dry_run"] and not _table_exists(conn, "icon_observations"):
            from fr24.rlsm_icons import ensure_schema
            ensure_schema(conn)
            info["icon_observations"] = "created"

    # 5) Preprocess stamp: rows produced under a different mode/scale than the
    #    current ZONE_OCR_CONFIG. Resume keys on screenshots.ocr_status, so a
    #    stale row is skipped forever unless it is counted and re-read here.
    if conn is not None and _table_exists(conn, "ocr_observations"):
        if not ctx["dry_run"]:
            from fr24.rlsm_preprocess import ensure_observation_columns
            added = ensure_observation_columns(conn)
            if added:
                info["ocr_observations_columns_added"] = added
        cols = {r[1] for r in conn.execute("PRAGMA table_info(ocr_observations)")}
        if {"preprocess", "preprocess_scale"} <= cols:
            from fr24.rlsm_preprocess import config_stamp
            from fr24.rlsm_zones import ZONE_OCR_CONFIG
            want_mode, want_scale = config_stamp(ZONE_OCR_CONFIG.get("label_layer", {}))
            stale_pp = _count(conn, """
                SELECT COUNT(*) FROM ocr_observations o
                WHERE o.obs_id IN (SELECT MAX(obs_id) FROM ocr_observations
                                   WHERE zone='label_layer' GROUP BY screenshot_id)
                  AND (o.preprocess IS NULL OR o.preprocess <> ?
                       OR o.preprocess_scale IS NULL
                       OR ABS(o.preprocess_scale - ?) > 1e-6)""",
                (want_mode, want_scale))
            info["observations_needing_preprocess"] = stale_pp
            if stale_pp:
                warnings.append(
                    f"{stale_pp:,} screenshots were OCR'd under different "
                    f"preprocessing than ZONE_OCR_CONFIG now declares "
                    f"({want_mode} @ {want_scale}x). The ocr stage will re-read "
                    f"them (--reocr-stale-preprocess); existing raw OCR is kept "
                    f"and new rows append under a fresh run_id.")

    # 6) Word-box migration needed?
    if conn is not None and _table_exists(conn, "ocr_observations"):
        stale = _count(conn, """
            SELECT COUNT(*) FROM ocr_observations o
            WHERE o.obs_id IN (SELECT MAX(obs_id) FROM ocr_observations
                               WHERE zone='label_layer' GROUP BY screenshot_id)
              AND COALESCE(o.raw_lines_json,'') IN ('','[]')""")
        info["screenshots_needing_word_boxes"] = stale
        if stale:
            warnings.append(
                f"{stale:,} screenshots were OCR'd before word boxes were captured. "
                f"Pins need that geometry, so the ocr stage will re-read them "
                f"(--reocr-boxes). Existing raw OCR is kept; new rows are appended "
                f"under a fresh run_id.")

    # 6) Disk headroom — word boxes add roughly 8 KB per screenshot.
    if conn is not None and _table_exists(conn, "screenshots"):
        info["screenshots_inventoried"] = _count(conn, "SELECT COUNT(*) FROM screenshots")
    try:
        free_mb = shutil.disk_usage(REPO).free / (1024 * 1024)
        info["disk_free_mb"] = round(free_mb)
        if free_mb < 500:
            warnings.append(f"only {free_mb:.0f} MB free — the word-box columns add "
                            f"roughly 100 MB over a 13k-image corpus")
    except OSError:
        # Disk headroom is advisory: on a platform where statvfs is unavailable
        # or the path is not stat-able we simply omit the figure rather than
        # block a run that would otherwise succeed.
        pass

    if conn is not None:
        conn.close()

    for w in warnings:
        print(f"    ! {w}", flush=True)
    if problems:
        for p in problems:
            print(f"    ✗ {p}", flush=True)
        raise StageError(f"{len(problems)} precondition(s) failed")
    print(f"    ✓ preflight ok: {json.dumps(info)}", flush=True)
    ctx["preflight"] = info
    return info


# --------------------------------------------------------------------------- #
# stages
# --------------------------------------------------------------------------- #

def stage_inventory(ctx: dict) -> None:
    args = ["--budget-sec", str(ctx["budget_sec"])]
    _run_script(REPO / "scripts" / "rlsm_inventory.py", args)


def stage_ocr(ctx: dict) -> None:
    common = ["--workers", str(ctx["workers"]), "--budget-sec", str(ctx["budget_sec"])]
    if ctx["limit"]:
        common += ["--limit", str(ctx["limit"])]
    # Pass 1: anything never OCR'd.
    _run_module("fr24.rlsm_ocr_parallel", common)
    # Pass 2: rows that predate word-box capture, which pins need for geometry.
    if ctx["preflight"].get("screenshots_needing_word_boxes"):
        print("    · backfilling word boxes on pre-existing OCR rows", flush=True)
        _run_module("fr24.rlsm_ocr_parallel", common + ["--reocr-boxes"])
    # Pass 3: rows whose preprocessing no longer matches the zone config.
    if ctx["preflight"].get("observations_needing_preprocess"):
        print("    · re-reading rows OCR'd under stale preprocessing", flush=True)
        _run_module("fr24.rlsm_ocr_parallel", common + ["--reocr-stale-preprocess"])


def stage_aircraft(ctx: dict) -> None:
    args = ["--kind", "aircraft"]
    if ctx["limit"]:
        args += ["--limit", str(ctx["limit"])]
    _run_module("fr24.rlsm_extractors", args)


def stage_pins(ctx: dict) -> None:
    args = ["--kind", "labeled_poi", "--reset-labeled-pins"]
    if ctx["limit"]:
        args += ["--limit", str(ctx["limit"])]
    _run_module("fr24.rlsm_extractors", args)


def stage_icons(ctx: dict) -> None:
    args = ["--budget-sec", str(ctx["budget_sec"])]
    if ctx["limit"]:
        args += ["--limit", str(ctx["limit"])]
    _run_module("fr24.rlsm_icons", args)
    _run_script(REPO / "scripts" / "rlsm_icon_cluster.py", [])


def stage_geocode(ctx: dict) -> None:
    _run_script(REPO / "scripts" / "rlsm_geocode_unlabeled.py", [])


def stage_review(ctx: dict) -> None:
    _run_module("fr24.rlsm_extractors", ["--kind", "review_queue"])


def stage_export(ctx: dict) -> None:
    _run_module("fr24.rlsm_export", [])
    _run_module("fr24.rlsm_coverage", [])


def stage_unlabeled(ctx: dict) -> None:
    args = ["--budget-sec", str(ctx["budget_sec"])]
    if ctx["limit"]:
        args += ["--limit", str(ctx["limit"])]
    _run_module("fr24.rlsm_unlabeled", args)


def stage_report(ctx: dict) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build_report(), encoding="utf-8")
    print(f"    ✓ wrote {REPORT.relative_to(REPO)}", flush=True)


STAGE_FUNCS: dict = {
    "preflight": preflight,
    "inventory": stage_inventory,
    "ocr":       stage_ocr,
    "aircraft":  stage_aircraft,
    "pins":      stage_pins,
    "icons":     stage_icons,
    "geocode":   stage_geocode,
    "review":    stage_review,
    "export":    stage_export,
    "unlabeled": stage_unlabeled,
    "report":    stage_report,
}


# --------------------------------------------------------------------------- #
# status + report
# --------------------------------------------------------------------------- #

def collect_status() -> dict:
    if not DB.exists():
        return {"db": str(DB.relative_to(REPO)), "exists": False}
    conn = _connect()
    if not _table_exists(conn, "screenshots"):
        conn.close()
        return {"db": str(DB.relative_to(REPO)), "exists": True, "schema": False}

    st: dict = {"db": str(DB.relative_to(REPO)), "exists": True, "schema": True}
    st["screenshots"] = _count(conn, "SELECT COUNT(*) FROM screenshots")
    st["ocr_status"] = {
        r[0]: r[1] for r in conn.execute(
            "SELECT ocr_status, COUNT(*) FROM screenshots GROUP BY 1")
    }
    st["ocr_observations"] = _count(conn, "SELECT COUNT(*) FROM ocr_observations")
    st["ocr_with_word_boxes"] = _count(
        conn, "SELECT COUNT(*) FROM ocr_observations "
              "WHERE COALESCE(raw_lines_json,'') NOT IN ('','[]')")
    st["aircraft_observations"] = _count(conn, "SELECT COUNT(*) FROM aircraft_observations")

    st["labeled_pins"] = _count(conn, "SELECT COUNT(*) FROM labeled_pins")
    st["labeled_pins_located"] = _count(
        conn, "SELECT COUNT(*) FROM labeled_pins WHERE centroid_x IS NOT NULL")
    st["distinct_labels"] = _count(
        conn, "SELECT COUNT(DISTINCT normalized_label) FROM labeled_pins")
    st["screenshots_with_2plus_located_pins"] = _count(conn, """
        SELECT COUNT(*) FROM (SELECT screenshot_id FROM labeled_pins
        WHERE centroid_x IS NOT NULL GROUP BY screenshot_id HAVING COUNT(*) >= 2)""")

    if _table_exists(conn, "icon_observations"):
        st["icons"] = _count(conn, "SELECT COUNT(*) FROM icon_observations")
        st["icon_clusters"] = _count(
            conn, "SELECT COUNT(DISTINCT cluster_id) FROM icon_observations "
                  "WHERE cluster_id IS NOT NULL")
        st["icon_named"] = _count(
            conn, "SELECT COUNT(*) FROM icon_observations "
                  "WHERE icon_class IS NOT NULL AND icon_class != ''")
        st["pins_with_icon"] = _count(
            conn, "SELECT COUNT(DISTINCT pin_id) FROM icon_observations "
                  "WHERE pin_id IS NOT NULL")

    st["unlabeled_candidates"] = _count(conn, "SELECT COUNT(*) FROM unlabeled_pin_candidates")
    st["review_queue"] = {
        r[0]: r[1] for r in conn.execute(
            "SELECT item_kind, COUNT(*) FROM manual_review_queue GROUP BY 1 ORDER BY 2 DESC")
    }
    st["runs"] = [
        {"run_kind": r[0], "status": r[1], "n_processed": r[2], "ended_at": r[3]}
        for r in conn.execute(
            "SELECT run_kind, status, n_processed, ended_at FROM processing_runs "
            "ORDER BY run_id DESC LIMIT 8")
    ]
    conn.close()
    return st


def build_report() -> str:
    st = collect_status()
    L: list[str] = ["# RLSM run report", "",
                    f"Generated {_iso_now()} by `fr24/rlsm_pipeline.py`.", ""]

    if not st.get("schema"):
        L += ["No populated database yet — run `./run-rlsm.sh`.", ""]
        return "\n".join(L)

    L += ["## Corpus", "",
          "| metric | value |", "|---|---|",
          f"| screenshots inventoried | {st['screenshots']:,} |",
          f"| OCR observations | {st['ocr_observations']:,} |",
          f"| ...carrying word boxes | {st['ocr_with_word_boxes']:,} |",
          f"| aircraft observations | {st['aircraft_observations']:,} |", ""]

    total = st["labeled_pins"] or 0
    located = st["labeled_pins_located"] or 0
    pct = (100.0 * located / total) if total else 0.0
    L += ["## Labels", "",
          "| metric | value |", "|---|---|",
          f"| labeled pins | {total:,} |",
          f"| ...with pixel geometry | {located:,} ({pct:.1f}%) |",
          f"| distinct normalized labels | {st['distinct_labels']:,} |",
          f"| screenshots with >=2 located pins (affine-fittable) | "
          f"{st['screenshots_with_2plus_located_pins']:,} |", "",
          "> Geometry coverage is the number that matters for the affine geocoder:",
          "> it needs two located pins per frame. Distinct labels is the gazetteer",
          "> check — the old inline vocabulary capped it at 91.", ""]

    if "icons" in st:
        n_icons = st["icons"] or 0
        pins_with = st.get("pins_with_icon", 0) or 0
        share = (100.0 * pins_with / located) if located else 0.0
        L += ["## Icons", "",
              "| metric | value |", "|---|---|",
              f"| icon observations | {n_icons:,} |",
              f"| distinct glyph clusters | {st.get('icon_clusters', 0):,} |",
              f"| located pins carrying an icon | {pins_with:,} ({share:.1f}%) |",
              f"| icons assigned a named class | {st.get('icon_named', 0):,} |", ""]
        L += _icon_agreement_section()

    L += ["## Review queue", "", "| kind | rows |", "|---|---|"]
    for kind, n in (st.get("review_queue") or {}).items():
        L += [f"| {kind} | {n:,} |"]
    if not st.get("review_queue"):
        L += ["| _(empty)_ | 0 |"]
    L += ["",
          "> `labeled_pin_low_conf` should be far smaller than it was before the",
          "> Tier-2 suppression fix: every Tier-1 hit used to re-emit itself as an",
          "> overlapping 0.25-confidence unknown, under the 0.5 review threshold.", ""]

    L += ["## Recent runs", "", "| run_kind | status | processed | ended |", "|---|---|---|---|"]
    for r in st.get("runs", []):
        L += [f"| {r['run_kind']} | {r['status']} | {r['n_processed'] or 0:,} "
              f"| {r['ended_at'] or '—'} |"]
    L += [""]
    return "\n".join(L)


def _icon_agreement_section() -> list[str]:
    """Agreement between named icon class and the label's gazetteer type."""
    conn = _connect()
    if not _table_exists(conn, "icon_observations"):
        conn.close()
        return []
    rows = conn.execute("""
        SELECT i.icon_class, p.pin_type_guess, COUNT(*) n
        FROM icon_observations i JOIN labeled_pins p ON p.pin_id = i.pin_id
        WHERE i.icon_class IS NOT NULL AND i.icon_class != ''
        GROUP BY 1, 2 ORDER BY n DESC LIMIT 15""").fetchall()
    conn.close()
    if not rows:
        return ["_Icon/vocabulary agreement is reported once clusters are named:_",
                "_edit `data/reference/icon_classes.json`, then_",
                "_`python3 scripts/rlsm_icon_cluster.py --apply`._", ""]
    out = ["### Icon class vs label type", "",
           "| icon class | label type | count |", "|---|---|---|"]
    out += [f"| {a} | {b} | {n:,} |" for a, b, n in rows]
    out += ["",
            "> An airport glyph beside a garbled string that fuzzy-matched a",
            "> municipio is a contradiction worth flagging; the same glyph beside",
            "> TJSJ is confirmation. With a 5,700-key gazetteer this class prior is",
            "> what keeps fuzzy matching honest.", ""]
    return out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def resolve_stages(args: argparse.Namespace) -> list[str]:
    if args.stage:
        if args.stage not in STAGE_FUNCS:
            raise SystemExit(f"unknown stage {args.stage!r}; "
                             f"choose from {', '.join(STAGE_FUNCS)}")
        # A single stage still gets preflight, unless it is preflight itself.
        return [args.stage] if args.stage == "preflight" else ["preflight", args.stage]

    stages = list(DEFAULT_STAGES)
    if args.from_stage:
        if args.from_stage not in stages:
            raise SystemExit(f"unknown stage {args.from_stage!r}; "
                             f"choose from {', '.join(stages)}")
        stages = ["preflight"] + stages[stages.index(args.from_stage):]
        stages = list(dict.fromkeys(stages))
    if args.skip_icons and "icons" in stages:
        stages.remove("icons")
    return stages


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="run-rlsm.sh",
        description="Run the whole RLSM screenshot extraction pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Stages: " + ", ".join(ALL_STAGES) +
               "\nOptional (not run by default): " + ", ".join(OPTIONAL_STAGES))
    ap.add_argument("--workers", type=int, default=4,
                    help="Parallel OCR workers (default 4).")
    ap.add_argument("--budget-sec", type=float, default=86400.0,
                    help="Per-stage wall-clock budget in seconds (default 24h).")
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap images per stage — use for a smoke test.")
    ap.add_argument("--stage", type=str, default="",
                    help="Run exactly one stage (preflight still runs first).")
    ap.add_argument("--from", dest="from_stage", type=str, default="",
                    help="Resume from this stage onward.")
    ap.add_argument("--skip-icons", action="store_true",
                    help="Skip the icon detection stage.")
    ap.add_argument("--status", action="store_true",
                    help="Print pipeline state as JSON and exit.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the stage plan and run preflight only.")
    args = ap.parse_args()

    if args.status:
        print(json.dumps(collect_status(), indent=2))
        return 0

    stages = resolve_stages(args)
    ctx = {
        "workers": args.workers, "budget_sec": args.budget_sec,
        "limit": args.limit, "dry_run": args.dry_run,
        "stages": stages, "preflight": {},
    }

    print(f"[rlsm] plan: {' -> '.join(stages)}", flush=True)
    if args.limit:
        print(f"[rlsm] limit={args.limit} (smoke test)", flush=True)

    t_all = time.time()
    for i, name in enumerate(stages, 1):
        header = f"[rlsm] {i}/{len(stages)} {name}"
        if args.dry_run and name != "preflight":
            print(f"{header} — skipped (--dry-run)", flush=True)
            continue
        print(header, flush=True)
        t0 = time.time()
        try:
            STAGE_FUNCS[name](ctx)
        except StageError as exc:
            print(f"[rlsm] FAILED at stage {name}: {exc}", file=sys.stderr, flush=True)
            print("[rlsm] fix the above, then resume with "
                  f"`./run-rlsm.sh --from {name}`", file=sys.stderr, flush=True)
            return 1
        except KeyboardInterrupt:
            print(f"\n[rlsm] interrupted during {name}. Every stage is resumable — "
                  f"re-run `./run-rlsm.sh --from {name}`.", file=sys.stderr, flush=True)
            return 130
        print(f"[rlsm] {name} done in {time.time() - t0:.1f}s", flush=True)

    print(f"[rlsm] complete in {time.time() - t_all:.1f}s", flush=True)
    if not args.dry_run and REPORT.exists():
        print(f"[rlsm] report: {REPORT.relative_to(REPO)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
