#!/usr/bin/env python3
"""
FR24 ground-truth harvest controller — enforces the safe, quota-aware protocol.

WHY THIS EXISTS
---------------
On 2026-06-11 a batched harvest fetched 25 tracks (spending the whole daily
FR24 export quota) but only 1 file actually saved: each download was aborted
when the browser immediately navigated to the next flight. Quota counts the
FETCH, not the save, so 24 quota units were burned for nothing.

This controller makes that failure mode structurally impossible by enforcing a
ONE-AT-A-TIME, VERIFY-BEFORE-ADVANCE loop with a persistent daily ledger:

    for each target (NEVER more than one fetch outstanding):
        1) `next`              -> get exactly one target (skips already-saved,
                                  refuses once the daily cap is reached)
        2) <agent fetches it in the browser and triggers the CSV download>
        3) `commit T D ID`     -> poll ~/Downloads, VALIDATE the file, move it
                                  into ground_truth, increment the ledger.
                                  Exit 0 = saved. Exit 2 = not found/invalid.
        4) if commit failed -> STOP. Do not fetch anything else this run.

Because `commit` is gated on the file actually being on disk, a lost download
is caught after ONE wasted fetch instead of 25. The ledger caps fetches at
DAILY_QUOTA and is idempotent: re-running after a crash never re-burns quota on
flights already saved.

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
HEX_RE = re.compile(r"^[0-9a-f]{6,8}$")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GT = os.path.join(REPO, "data", "ground_truth")
LEDGER = os.path.join(GT, "_harvest_ledger.json")
DNR_GLOB = os.path.join(GT, "*", "_carryover_next_quota.csv")  # "no FR24 track" lists


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
    return q


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


def cmd_next(args):
    led = load_ledger()
    if led["exhausted"] or remaining(led) <= 0:
        print(f"STOP: daily quota reached ({led['used_today']}/{DAILY_QUOTA}). "
              f"Resume after reset.", file=sys.stderr)
        sys.exit(3)
    q = load_queue()
    if not q:
        print("STOP: queue empty (nothing left to harvest).", file=sys.stderr)
        sys.exit(4)
    n = min(args.count, remaining(led), len(q))
    if args.count > 1:
        print(f"WARNING: protocol is one-at-a-time. Fetch ONE, commit, then ask "
              f"for the next. Showing {n} for planning only.", file=sys.stderr)
    for t in q[:n]:
        url = ("https://api.flightradar24.com/common/v1/flight-playback.json"
               f"?flightId={t['flight_id']}&token=<TOKEN>")
        print(json.dumps({**t, "playback_url": url}))


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


def _plus1(d: str) -> str:
    try:
        return (datetime.date.fromisoformat(d) + datetime.timedelta(days=1)).isoformat()
    except Exception:
        return d


def cmd_commit(args):
    tail, date, fid = args.tail.upper(), args.date, args.flight_id.lower()
    led = load_ledger()

    # idempotent: already saved -> success, no quota change
    if fid in harvested_ids():
        print(f"OK (already harvested): {tail} {date} {fid}")
        sys.exit(0)

    dl = find_downloads()
    expect = f"{tail}_{date}_{fid}.csv"
    src = os.path.join(dl, expect)

    # poll for the download to land
    deadline = time.time() + args.wait
    while time.time() < deadline:
        if os.path.exists(src) and not os.path.exists(src + ".crdownload"):
            break
        time.sleep(0.5)

    if not os.path.exists(src):
        # the fetch still cost 1 quota unit even though nothing saved -> record it
        led["used_today"] += 1
        if led["used_today"] >= DAILY_QUOTA:
            led["exhausted"] = True
        save_ledger(led)
        print(f"FAIL: '{expect}' not found in {dl} after {args.wait}s. "
              f"Download was lost (quota spent). used_today={led['used_today']}. "
              f"STOP this run — do not fetch more.", file=sys.stderr)
        sys.exit(2)

    ok, msg, pts = _validate(src, tail, date)
    if not ok:
        led["used_today"] += 1
        if led["used_today"] >= DAILY_QUOTA:
            led["exhausted"] = True
        save_ledger(led)
        # quarantine the bad file so it isn't mistaken for a good track
        qdir = os.path.join(GT, "_quarantine")
        os.makedirs(qdir, exist_ok=True)
        try:
            _relocate(src, os.path.join(qdir, expect))
        except Exception:
            pass
        if "quota-empty" in msg or "only" in msg:
            led["exhausted"] = True
            save_ledger(led)
            print(f"FAIL: {msg}. Looks like quota exhaustion. used_today={led['used_today']}. "
                  f"STOP this run.", file=sys.stderr)
        else:
            print(f"FAIL: {msg}. used_today={led['used_today']}. STOP this run.", file=sys.stderr)
        sys.exit(2)

    # success: move into ground_truth, count the quota unit
    dest_dir = os.path.join(GT, tail)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, expect)
    _relocate(src, dest)
    led["used_today"] += 1
    led["saved_today"].append(fid)
    if led["used_today"] >= DAILY_QUOTA:
        led["exhausted"] = True
    save_ledger(led)
    print(f"OK: saved {tail} {date} {fid} ({pts} pts) -> {os.path.relpath(dest, REPO)}  "
          f"| {msg} | used_today={led['used_today']}/{DAILY_QUOTA}")
    sys.exit(0)


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


def main():
    ap = argparse.ArgumentParser(description="FR24 harvest controller (safe protocol).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(func=cmd_status)
    n = sub.add_parser("next"); n.add_argument("--count", type=int, default=1); n.set_defaults(func=cmd_next)
    c = sub.add_parser("commit")
    c.add_argument("tail"); c.add_argument("date"); c.add_argument("flight_id")
    c.add_argument("--wait", type=float, default=8.0)
    c.set_defaults(func=cmd_commit)
    m = sub.add_parser("miss")
    m.add_argument("tail"); m.add_argument("date"); m.add_argument("flight_id")
    m.add_argument("reason", choices=["quota", "nocoverage", "other"])
    m.set_defaults(func=cmd_miss)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
