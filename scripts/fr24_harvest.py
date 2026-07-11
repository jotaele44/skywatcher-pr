#!/usr/bin/env python3
"""
FR24 ground-truth harvest controller — enforces the safe, quota-aware protocol.

WHY THIS EXISTS
---------------
On 2026-06-11 a batched harvest fetched 25 tracks (spending the whole daily
FR24 export quota) but only 1 file actually saved: each download was aborted
when the browser immediately navigated to the next flight. Quota counts the
FETCH, not the save, so 24 quota units were burned for nothing.

This controller makes that failure mode structurally impossible by gating every
advance on the file actually being on disk, with a persistent daily ledger that
hard-stops at DAILY_QUOTA and is idempotent (re-runs never re-burn quota on
flights already saved).

TWO WAYS TO DRIVE IT
--------------------
1) Strict one-at-a-time (legacy, max safety):
       next -> click CSV+KML in browser -> commit TAIL DATE FID   (repeat)
2) Low-credit batch (keeps the model out of the per-flight loop):
       plan --count N            -> JSON targets grouped by tail
       <inject scripts/fr24_batch_click.js once per tail; it clicks every
        flight's CSV+KML on the loaded aircraft page — NO navigation>
       commit-batch              -> finalize every native download now on disk
   The fetching (quota spend) happens in the browser; commit-batch only reads
   files already on disk, so it costs no quota and can be re-run safely.

NATIVE EXPORT (confirmed 2026-06-17)
------------------------------------
FR24's per-flight CSV/KML buttons download files named <FLIGHTID>.csv /
<FLIGHTID>.kml to ~/Downloads. CSV+KML are metered separately => a CSV+KML
flight costs 2 quota units; 25/day => 12 flights/batch with 1 unit reserve.
commit accepts the native <flightid>.* names and files them as
ground_truth/<TAIL>/<TAIL>_<DATE>_<FLIGHTID>.csv/.kml.

CSV is the source of truth for "harvested". KML is best-effort: a valid CSV is
always filed even if its KML is missing/stub (older flights are CSV-only
anyway; KML backfill is a separate opt-in). The flight still costs 2 units
because both buttons were clicked/metered.

Stdlib only. Safe to run repeatedly.
"""
from __future__ import annotations
import argparse, csv, datetime, glob, json, os, re, shutil, sys, time


def _relocate(src: str, dst: str) -> None:
    """Move that works across mounts. Downloads and the repo are different
    devices, and the Downloads mount may forbid unlink — so copy, then try to
    remove the source but never fail if removal isn't permitted."""
    shutil.copy2(src, dst)
    try:
        os.remove(src)
    except OSError:
        pass  # leave the original in Downloads; harmless

DAILY_QUOTA = 25
CANON_HEADER = "Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction"
MIN_POINTS = 3                      # a real track has more than a couple of fixes
KML_MIN_BYTES = 500                 # a real KML has placemarks; a stub is tiny
HEX_RE = re.compile(r"^[0-9a-f]{6,8}$")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GT = os.path.join(REPO, "data", "ground_truth")
LEDGER = os.path.join(GT, "_harvest_ledger.json")
DNR_GLOB = os.path.join(GT, "*", "_carryover_next_quota.csv")  # "no FR24 track" lists

# ---------------------------------------------------------------- priority tails
# Aircraft that must not be lost to the rolling Gold history floor. A flight from
# one of these tails is bumped to the FRONT of the queue once it is within
# EXPIRY_BUMP_DAYS of aging out (date + GOLD_WINDOW_DAYS <= today + EXPIRY_BUMP_DAYS).
# Outside that window it keeps its normal oldest-first position.
PRIORITY_TAILS = {"N409TD", "N999ZY", "N767PD", "N407PR"}
GOLD_WINDOW_DAYS = 365   # FR24 Gold rolling history window (oldest fetchable = today-365)
EXPIRY_BUMP_DAYS = 2     # bump a priority-tail flight this many days before it ages out


# ---------------------------------------------------------------- downloads dir
def find_downloads() -> str:
    cands = []
    env = os.environ.get("FR24_DOWNLOADS")
    if env:
        cands.append(env)
    cands += sorted(glob.glob("/sessions/*/mnt/Downloads"))
    cands.append(os.path.expanduser("~/Downloads"))
    cands.append("/Users/jotaele/Downloads")
    for c in cands:
        if c and os.path.isdir(c):
            return c
    return os.path.expanduser("~/Downloads")


# ---------------------------------------------------------------- ledger
def today() -> str:
    return datetime.date.today().isoformat()


def load_ledger() -> dict:
    try:
        led = json.load(open(LEDGER))
    except Exception:
        led = {}
    if led.get("date") != today():
        led = {"date": today(), "used_today": 0, "saved_today": [], "exhausted": False}
        save_ledger(led)
    led.setdefault("used_today", 0)
    led.setdefault("saved_today", [])
    led.setdefault("exhausted", False)
    return led


def save_ledger(led: dict) -> None:
    os.makedirs(GT, exist_ok=True)
    tmp = LEDGER + ".tmp"
    json.dump(led, open(tmp, "w"), indent=1)
    os.replace(tmp, LEDGER)


def remaining(led: dict) -> int:
    return max(0, DAILY_QUOTA - led["used_today"])


def _cap(led: dict) -> None:
    if led["used_today"] >= DAILY_QUOTA:
        led["exhausted"] = True


# ---------------------------------------------------------------- harvested index
def harvested_ids() -> set:
    ids = set()
    for f in glob.glob(os.path.join(GT, "*", "*.csv")):
        b = os.path.basename(f)
        if b.startswith("_"):
            continue
        for tok in re.findall(r"([0-9a-f]{7,8})", b):
            ids.add(tok)
    # summary.csv flight_id column
    summ = os.path.join(GT, "summary.csv")
    if os.path.exists(summ):
        try:
            for row in csv.DictReader(open(summ)):
                fid = (row.get("flight_id") or "").strip()
                if HEX_RE.match(fid):
                    ids.add(fid)
        except Exception:
            pass
    return ids


def do_not_requeue() -> set:
    dnr = set()
    for f in glob.glob(DNR_GLOB):
        try:
            for row in csv.DictReader(open(f)):
                note = (row.get("note") or "").lower()
                if "no fr24 track" in note or "no ads-b" in note:
                    dnr.add((os.path.basename(os.path.dirname(f)), row.get("date", "")))
        except Exception:
            pass
    return dnr


# ---------------------------------------------------------------- queue
def latest_carryover() -> str | None:
    cands = sorted(glob.glob(os.path.join(GT, "_harvest_carryover_*.csv")))
    return cands[-1] if cands else None


def _days_to_expiry(date: str, today: "datetime.date | None" = None) -> "int | None":
    """Days until this flight ages out of the Gold window (date + window - today).
    Negative once it has dropped below the floor; None if the date won't parse."""
    try:
        d = datetime.date.fromisoformat(date)
    except Exception:
        return None
    today = today or datetime.date.today()
    return (d + datetime.timedelta(days=GOLD_WINDOW_DAYS) - today).days


def prioritize_queue(q: list[dict], today: "datetime.date | None" = None) -> list[dict]:
    """Stable reordering: priority-tail flights that are within EXPIRY_BUMP_DAYS of
    aging out of the Gold window are bumped to the FRONT (soonest-expiry first); every
    other entry keeps its existing carryover order. A priority tail OUTSIDE that window
    is not bumped — it stays in its normal oldest-first slot."""
    def near_expiry_priority(e: dict) -> bool:
        if (e.get("tail") or "").upper() not in PRIORITY_TAILS:
            return False
        d = _days_to_expiry(e.get("date", ""), today)
        return d is not None and 0 <= d <= EXPIRY_BUMP_DAYS
    front = sorted((e for e in q if near_expiry_priority(e)), key=lambda e: e.get("date", ""))
    rest = [e for e in q if not near_expiry_priority(e)]
    return front + rest


def load_queue() -> list[dict]:
    """Prioritized list of {date,tail,flight_id} from the newest carryover file,
    with already-harvested and do-not-requeue entries filtered out."""
    path = latest_carryover()
    if not path:
        return []
    have = harvested_ids()
    dnr = do_not_requeue()
    q = []
    for row in csv.DictReader(open(path)):
        fid = (row.get("flight_id") or "").strip()
        tail = (row.get("tail") or "").strip()
        date = (row.get("date") or "").strip()
        if not HEX_RE.match(fid):
            continue
        if fid in have:
            continue
        if (tail, date) in dnr:
            continue
        q.append({"date": date, "tail": tail, "flight_id": fid})
    return prioritize_queue(q)


# ---------------------------------------------------------------- validation
def _plus1(d: str) -> str:
    try:
        return (datetime.date.fromisoformat(d) + datetime.timedelta(days=1)).isoformat()
    except Exception:
        return d


def _validate(path: str, tail: str, date: str) -> tuple[bool, str, int]:
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except Exception as e:
        return False, f"unreadable: {e}", 0
    if not lines or lines[0].strip() != CANON_HEADER:
        return False, "bad/missing header", 0
    data = [ln for ln in lines[1:] if ln.strip()]
    if len(data) < MIN_POINTS:
        return False, f"only {len(data)} data rows (quota-empty or stub track)", len(data)
    # soft checks (warn only): callsign + date
    warn = []
    first = data[0].split(",")
    if len(first) >= 3 and tail.upper() not in first[2].upper():
        warn.append(f"callsign={first[2]!r}!={tail}")
    m = re.search(r"(\d{4}-\d{2}-\d{2})", first[1] if len(first) > 1 else "")
    if m and m.group(1) not in (date, _plus1(date)):
        warn.append(f"utc_date={m.group(1)}!={date}")
    return True, ("ok" + (" [WARN " + "; ".join(warn) + "]" if warn else "")), len(data)


def _validate_kml(path: str) -> tuple[bool, str, int]:
    try:
        b = os.path.getsize(path)
    except OSError:
        return False, "missing", 0
    if b < KML_MIN_BYTES:
        return False, f"kml too small ({b}B; quota-empty/stub)", b
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except Exception as e:
        return False, f"kml unreadable: {e}", b
    if "<Placemark" not in txt or "coordinates" not in txt.lower():
        return False, "kml missing Placemark/coordinates", b
    return True, f"kml ok ({b}B)", b


# ---------------------------------------------------------------- downloads lookup
def _locate(dl: str, fid: str, ext: str, tail: str | None = None, date: str | None = None) -> str | None:
    """Find a finished download for this flight. Accepts the native FR24 name
    <flightid>.<ext>, the filed name <TAIL>_<DATE>_<flightid>.<ext>, and any
    "*<flightid>*.<ext>" (e.g. browser dedupe "name (1).csv"). Ignores partials."""
    names = [f"{fid}.{ext}"]
    if tail and date:
        names.append(f"{tail.upper()}_{date}_{fid}.{ext}")
    for nm in names:
        p = os.path.join(dl, nm)
        if os.path.exists(p) and not os.path.exists(p + ".crdownload"):
            return p
    g = [x for x in glob.glob(os.path.join(dl, f"*{fid}*.{ext}"))
         if not os.path.exists(x + ".crdownload")]
    return max(g, key=os.path.getmtime) if g else None


def _quarantine(src: str | None, name: str) -> None:
    if not src or not os.path.exists(src):
        return
    qdir = os.path.join(GT, "_quarantine")
    os.makedirs(qdir, exist_ok=True)
    try:
        _relocate(src, os.path.join(qdir, name))
    except Exception:
        pass


# ---------------------------------------------------------------- commit core
def _commit_one(led: dict, tail: str, date: str, fid: str,
                no_kml: bool, wait: float) -> tuple[str, str]:
    """Finalize one flight from files already in (or landing in) ~/Downloads.
    Returns (status, detail). status in:
      saved | already | lost | stub | badcsv
    Updates and persists the ledger. unit cost = 1 (no-kml) else 2, charged
    whenever the buttons were metered (i.e. always except 'already')."""
    tail, fid = tail.upper(), fid.lower()
    if fid in harvested_ids():
        return ("already", f"{tail} {date} {fid}")

    dl = find_downloads()
    unit = 1 if no_kml else 2

    # poll for the CSV to land
    csv_src = _locate(dl, fid, "csv", tail, date)
    deadline = time.time() + wait
    while not csv_src and time.time() < deadline:
        time.sleep(0.5)
        csv_src = _locate(dl, fid, "csv", tail, date)

    if not csv_src:
        led["used_today"] += unit; _cap(led); save_ledger(led)
        return ("lost", f"CSV for {fid} not found in {dl} (quota spent)")

    ok, msg, pts = _validate(csv_src, tail, date)
    if not ok:
        led["used_today"] += unit
        if "quota-empty" in msg or "only" in msg:
            led["exhausted"] = True
        _cap(led); save_ledger(led)
        _quarantine(csv_src, f"{tail}_{date}_{fid}.csv")
        return ("stub" if ("quota-empty" in msg or "only" in msg) else "badcsv", msg)

    # KML is best-effort: file it when valid, else file CSV-only.
    kml_note = "no-kml mode"
    kml_src = None
    if not no_kml:
        kml_src = _locate(dl, fid, "kml", tail, date)
        kdead = time.time() + min(wait, 6)
        while not kml_src and time.time() < kdead:
            time.sleep(0.5)
            kml_src = _locate(dl, fid, "kml", tail, date)
        if kml_src:
            kok, kmsg, _kb = _validate_kml(kml_src)
            if not kok:
                _quarantine(kml_src, f"{tail}_{date}_{fid}.kml")
                kml_src = None
                kml_note = f"csv-only ({kmsg})"
            else:
                kml_note = kmsg
        else:
            kml_note = "csv-only (kml not found)"

    dest_dir = os.path.join(GT, tail)
    os.makedirs(dest_dir, exist_ok=True)
    _relocate(csv_src, os.path.join(dest_dir, f"{tail}_{date}_{fid}.csv"))
    if kml_src:
        _relocate(kml_src, os.path.join(dest_dir, f"{tail}_{date}_{fid}.kml"))

    led["used_today"] += unit
    led["saved_today"].append(fid)
    _cap(led); save_ledger(led)
    return ("saved", f"{pts} pts | {kml_note}")


# ---------------------------------------------------------------- commands
def cmd_status(_args):
    led = load_ledger()
    q = load_queue()
    dl = find_downloads()
    print(f"date={led['date']}  quota={DAILY_QUOTA}  used_today={led['used_today']}  "
          f"remaining={remaining(led)}  exhausted={led['exhausted']}")
    print(f"saved_today={led['saved_today']}")
    print(f"queue_remaining(after harvested/no-coverage filter)={len(q)}")
    print(f"downloads_dir={dl}")
    print(f"harvested_total={len(harvested_ids())}")
    if q[:5]:
        print("next up:")
        for t in q[:5]:
            print(f"   {t['date']} {t['tail']} {t['flight_id']}")


def cmd_plan(args):
    """Emit up to N affordable targets (respecting the 2-unit/flight budget),
    grouped by tail, as JSON for the in-page batch driver."""
    led = load_ledger()
    q = load_queue()
    unit = 1 if args.no_kml else 2
    budget = remaining(led) // unit
    n = max(0, min(args.count, budget, len(q)))
    sel = q[:n]
    by_tail: dict[str, list] = {}
    for t in sel:
        by_tail.setdefault(t["tail"], []).append({"date": t["date"], "flight_id": t["flight_id"]})
    out = {
        "date": led["date"],
        "used_today": led["used_today"],
        "remaining_units": remaining(led),
        "unit_cost": unit,
        "budget_flights": budget,
        "selected": n,
        "queue_remaining": len(q),
        "by_tail": [
            {"tail": k,
             "oldest_date": min(x["date"] for x in v),
             "flight_ids": [x["flight_id"] for x in v],
             "flights": v}
            for k, v in by_tail.items()
        ],
        "flat": sel,
    }
    print(json.dumps(out, indent=2))


def cmd_next(args):
    led = load_ledger()
    unit = 1 if args.no_kml else 2
    if led["exhausted"] or remaining(led) < unit:
        print(f"STOP: daily quota reached ({led['used_today']}/{DAILY_QUOTA}). "
              f"Resume after reset.", file=sys.stderr)
        sys.exit(3)
    q = load_queue()
    if not q:
        print("STOP: queue empty (nothing left to harvest).", file=sys.stderr)
        sys.exit(4)
    n = min(args.count, remaining(led) // unit, len(q))
    if args.count > 1:
        print(f"WARNING: one-at-a-time protocol. For batches use `plan` + the in-page "
              f"driver + `commit-batch`. Showing {n} for planning only.", file=sys.stderr)
    for t in q[:n]:
        print(json.dumps(t))


def cmd_commit(args):
    """Strict single-flight commit (legacy one-at-a-time path)."""
    led = load_ledger()
    status, detail = _commit_one(led, args.tail, args.date, args.flight_id,
                                 args.no_kml, args.wait)
    tail, date, fid = args.tail.upper(), args.date, args.flight_id.lower()
    if status == "saved":
        print(f"OK: saved {tail} {date} {fid} ({detail}) | used_today={led['used_today']}/{DAILY_QUOTA}")
        sys.exit(0)
    if status == "already":
        print(f"OK (already harvested): {tail} {date} {fid}")
        sys.exit(0)
    if status == "stub":
        print(f"FAIL: {detail}. Looks like quota exhaustion. used_today={led['used_today']}. "
              f"STOP this run.", file=sys.stderr)
        sys.exit(2)
    # lost / badcsv
    print(f"FAIL: {detail}. used_today={led['used_today']}. STOP this run — do not fetch more.",
          file=sys.stderr)
    sys.exit(2)


def cmd_commit_batch(args):
    """Finalize a whole batch from files already on disk. Costs no quota itself
    (the fetching already happened in the browser). Idempotent and resumable:
    already-saved flights are skipped; present+valid files are filed; missing or
    stub downloads are reported and left queued for a clean retry."""
    led = load_ledger()
    q = load_queue()
    by_fid = {t["flight_id"]: t for t in q}
    dl = find_downloads()
    unit = 1 if args.no_kml else 2

    if args.flight_ids:
        fids = [f.lower() for f in args.flight_ids]
    else:
        # everything queued that has a native CSV waiting in Downloads
        fids = [t["flight_id"] for t in q if _locate(dl, t["flight_id"], "csv", t["tail"], t["date"])]

    saved, lost, stub, skipped = [], [], [], []
    print(f"commit-batch: {len(fids)} candidate(s); used_today={led['used_today']}/{DAILY_QUOTA}")
    for fid in fids:
        if fid in harvested_ids():
            print(f"  - {fid}: already harvested (skip)")
            continue
        t = by_fid.get(fid)
        if not t:
            skipped.append(fid)
            print(f"  - {fid}: NOT in current queue (skip — pass TAIL/DATE via single commit)")
            continue
        if led["exhausted"] or remaining(led) < unit:
            skipped.append(fid)
            print(f"  - {fid}: quota reserve reached (skip)")
            continue
        status, detail = _commit_one(led, t["tail"], t["date"], fid, args.no_kml, args.wait)
        tag = {"saved": "SAVED", "already": "already", "lost": "LOST",
               "stub": "STUB/quota", "badcsv": "BAD"}.get(status, status.upper())
        print(f"  - {t['tail']} {t['date']} {fid}: {tag} | {detail} | used_today={led['used_today']}")
        if status == "saved":
            saved.append(fid)
        elif status == "stub":
            stub.append(fid)
        elif status in ("lost", "badcsv"):
            lost.append(fid)

    print(f"DONE: saved={len(saved)} lost/missing={len(lost)} stub/quota={len(stub)} "
          f"skipped={len(skipped)} | used_today={led['used_today']}/{DAILY_QUOTA} "
          f"exhausted={led['exhausted']}")
    if stub:
        print("NOTE: stub/quota-empty downloads detected -> FR24 daily quota likely exhausted. "
              "Stop fetching; re-run after reset.", file=sys.stderr)
    # exit 0 if at least something saved and nothing lost/stub; else 2 to signal attention
    sys.exit(0 if not (lost or stub) else 2)


def cmd_miss(args):
    """Record a fetch that returned no usable track (quota-empty, or genuine
    no-coverage). Always costs 1 quota unit."""
    tail, date, fid = args.tail.upper(), args.date, args.flight_id.lower()
    led = load_ledger()
    led["used_today"] += 1
    if args.reason == "quota" or led["used_today"] >= DAILY_QUOTA:
        led["exhausted"] = True
    save_ledger(led)
    if args.reason == "nocoverage":
        # append to the tail's do-not-requeue list
        dnr = os.path.join(GT, tail, "_carryover_next_quota.csv")
        os.makedirs(os.path.dirname(dnr), exist_ok=True)
        new = not os.path.exists(dnr)
        with open(dnr, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["date", "segments_remaining", "note"])
            w.writerow([date, 0, "no FR24 track found (in log batch but no ADS-B coverage) — do not re-queue"])
        print(f"recorded NO-COVERAGE {tail} {date} {fid}; used_today={led['used_today']}")
    else:
        print(f"recorded MISS({args.reason}) {tail} {date} {fid}; "
              f"used_today={led['used_today']}  exhausted={led['exhausted']}. "
              f"If quota: STOP this run.", file=sys.stderr)
    sys.exit(0)


def cmd_reconcile(args):
    """Rebuild today's ledger counters from reality. used_today is set to
    (flights saved today * unit) so the count reflects true FR24 spend after a
    bad/aborted run. Use --used to override the unit-derived value."""
    led = load_ledger()
    unit = 1 if args.no_kml else 2
    before = dict(led)
    if args.used is not None:
        led["used_today"] = max(0, args.used)
    else:
        led["used_today"] = len(led.get("saved_today", [])) * unit
    led["exhausted"] = led["used_today"] >= DAILY_QUOTA
    save_ledger(led)
    print(f"reconciled ledger: used_today {before.get('used_today')} -> {led['used_today']} "
          f"(saved_today={len(led.get('saved_today', []))}, unit={unit}) "
          f"exhausted={led['exhausted']}")
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser(description="FR24 harvest controller (safe protocol).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)

    p = sub.add_parser("plan")
    p.add_argument("--count", type=int, default=12)
    p.add_argument("--no-kml", action="store_true")
    p.set_defaults(func=cmd_plan)

    n = sub.add_parser("next")
    n.add_argument("--count", type=int, default=1)
    n.add_argument("--no-kml", action="store_true")
    n.set_defaults(func=cmd_next)

    c = sub.add_parser("commit")
    c.add_argument("tail"); c.add_argument("date"); c.add_argument("flight_id")
    c.add_argument("--wait", type=float, default=8.0)
    c.add_argument("--no-kml", action="store_true")
    c.set_defaults(func=cmd_commit)

    b = sub.add_parser("commit-batch")
    b.add_argument("flight_ids", nargs="*")
    b.add_argument("--wait", type=float, default=8.0)
    b.add_argument("--no-kml", action="store_true")
    b.set_defaults(func=cmd_commit_batch)

    m = sub.add_parser("miss")
    m.add_argument("tail"); m.add_argument("date"); m.add_argument("flight_id")
    m.add_argument("reason", choices=["quota", "nocoverage", "other"])
    m.set_defaults(func=cmd_miss)

    r = sub.add_parser("reconcile")
    r.add_argument("--used", type=int, default=None)
    r.add_argument("--no-kml", action="store_true")
    r.set_defaults(func=cmd_reconcile)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
