"""
RLSM map-icon channel.

FR24 draws a glyph next to most map labels — airport, heliport, aircraft,
navaid, city dot. Before this module those glyphs were not merely uncaptured,
they were *injected as noise*: Tesseract read them as junk characters (every
label_layer read in the corpus opens with debris like ``®fli htradar24 ©``) and
the old Tier-2 "capitalized word group" regex promoted some of that debris into
``unknown_label_candidate`` rows that landed in the review queue.

The existing blob pass (``fr24/rlsm_unlabeled.py``) half-sees them but is aimed
elsewhere: grayscale only — and colour is most of an icon's information — over a
crop thumbnailed to 480x540 (a ~22 px glyph arrives as ~8 px), typed with a
ground-feature taxonomy (``pad``, ``tank``, ``quarry``) that describes satellite
imagery rather than app chrome.

This pass is cheap only because pins now carry real geometry
(``fr24/rlsm_extractors.extract_labeled_pins``): the glyph is a deterministic
crop at a fixed offset from known text, so there is no search.

Three deliberate choices:

  * Crops come from the **original decoded RGB**, never a binarized or
    thresholded image. Binarizing throws away exactly the colour channel the
    icons encode meaning in.
  * The salience threshold is **percentile-adaptive per window**, because the
    basemap under a label ranges from dark ocean to bright urban fill.
  * Connected components are labelled in pure Python, matching the no-OpenCV
    posture of ``fr24/rlsm_unlabeled.py``. Windows are ~60x70 px, so this is
    far cheaper than that module's full-zone scan.

Each glyph is fingerprinted with a 64-bit average hash plus a circular-mean hue.
UI glyphs are pixel-identical between renders, so ``scripts/rlsm_icon_cluster.py``
collapses the corpus to a few dozen classes; the operator names each class once
and every recurrence inherits the type. That is the "review clusters, not items"
rule from docs/SCREENSHOT_DATA_STRATEGY.md §5, applied to icons.

CLI:
    python3 -m fr24.rlsm_icons [--budget-sec N] [--limit N] [--standalone]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from pathlib import Path

os.environ.setdefault("OMP_THREAD_LIMIT", "1")

# Guarded so the pure detector functions below (average_hash, circular_mean_hue,
# connected_components, detect_in_window) stay importable and unit-testable in
# environments without an image library. Only the plumbing needs Pillow.
try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - import guard
    Image = None  # type: ignore
    ImageOps = None  # type: ignore

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    # Optional: without it .heic screenshots cannot be decoded and are reported
    # as read failures by the caller. Preflight warns when it is absent, so the
    # operator learns about it before a run rather than from a stack trace here.
    pass

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"

# --- detector tuning ---------------------------------------------------------

# Glyph search window, expressed in multiples of the label's text height. FR24
# places the icon immediately left of the label, or centred above it.
WIN_LEFT_MULT = 2.2
WIN_UP_MULT = 1.4
WIN_DOWN_MULT = 0.4
WIN_RIGHT_MULT = 0.4     # slight overlap into the text, so a tight icon is not clipped

# A component must occupy between these fractions of the window to be a glyph.
MIN_AREA_FRAC = 0.010
MAX_AREA_FRAC = 0.55
MIN_AREA_PX = 24

# Salience percentile within the window. Icons are the most saturated / most
# luminance-deviant thing in their immediate neighbourhood.
SALIENCE_PERCENTILE = 0.88
SALIENCE_FLOOR = 28          # absolute floor so a flat window yields nothing

MAX_ICONS_PER_SCREENSHOT = 40

ICON_SCHEMA = """
CREATE TABLE IF NOT EXISTS icon_observations (
    icon_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id  INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    pin_id         INTEGER REFERENCES labeled_pins(pin_id),
    run_id         INTEGER REFERENCES processing_runs(run_id),
    bbox_x         INTEGER,
    bbox_y         INTEGER,
    bbox_w         INTEGER,
    bbox_h         INTEGER,
    centroid_x     INTEGER,
    centroid_y     INTEGER,
    area_px        INTEGER,
    aspect         REAL,
    fill_ratio     REAL,
    hue_deg        REAL,
    saturation     REAL,
    value          REAL,
    ahash          TEXT,
    cluster_id     INTEGER,
    icon_class     TEXT,
    confidence     REAL,
    review_status  TEXT NOT NULL DEFAULT 'unreviewed',
    observed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_icon_screenshot ON icon_observations(screenshot_id);
CREATE INDEX IF NOT EXISTS ix_icon_pin        ON icon_observations(pin_id);
CREATE INDEX IF NOT EXISTS ix_icon_ahash      ON icon_observations(ahash);
CREATE INDEX IF NOT EXISTS ix_icon_cluster    ON icon_observations(cluster_id);
"""


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create icon_observations in place on an already-built DB."""
    conn.executescript(ICON_SCHEMA)
    conn.commit()


# --- pure-function detector core --------------------------------------------
#
# Kept free of PIL types so it can be unit-tested on synthetic pixel arrays
# without an image library present.


def average_hash(gray: list[list[int]]) -> str:
    """64-bit average hash of a grayscale block, as 16 hex chars."""
    if not gray or not gray[0]:
        return "0" * 16
    h, w = len(gray), len(gray[0])
    cells: list[float] = []
    for by in range(8):
        for bx in range(8):
            y0, y1 = by * h // 8, max(by * h // 8 + 1, (by + 1) * h // 8)
            x0, x1 = bx * w // 8, max(bx * w // 8 + 1, (bx + 1) * w // 8)
            block = [gray[y][x] for y in range(y0, min(y1, h))
                     for x in range(x0, min(x1, w))]
            cells.append(sum(block) / len(block) if block else 0.0)
    mean = sum(cells) / len(cells)
    bits = 0
    for i, c in enumerate(cells):
        if c >= mean:
            bits |= 1 << (63 - i)
    return f"{bits:016x}"


def circular_mean_hue(hues: list[float], weights: list[float] | None = None) -> float:
    """
    Mean of hue angles in degrees. Hue is circular — the arithmetic mean of 350
    and 10 is 180 (cyan) when the answer is 0 (red) — so this averages unit
    vectors instead.
    """
    if not hues:
        return 0.0
    if weights is None:
        weights = [1.0] * len(hues)
    sx = sum(w * math.cos(math.radians(h)) for h, w in zip(hues, weights, strict=False))
    sy = sum(w * math.sin(math.radians(h)) for h, w in zip(hues, weights, strict=False))
    if sx == 0 and sy == 0:
        return 0.0
    # Round before the modulo: floating error otherwise turns an exact 0° into
    # 359.99999..., which reads as 360 and looks like a different hue.
    return round(math.degrees(math.atan2(sy, sx)), 6) % 360.0


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile; q in [0, 1]."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = q * (len(ordered) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return float(ordered[lo] * (1 - frac) + ordered[hi] * frac)


def connected_components(mask: list[list[bool]], min_area: int = 1) -> list[dict]:
    """
    Label 4-connected True regions. Iterative DFS, no OpenCV — same approach as
    fr24/rlsm_unlabeled._connected_components_threshold, over a much smaller
    window.
    """
    if not mask or not mask[0]:
        return []
    h, w = len(mask), len(mask[0])
    seen = [[False] * w for _ in range(h)]
    out: list[dict] = []
    for sy in range(h):
        for sx in range(w):
            if seen[sy][sx] or not mask[sy][sx]:
                seen[sy][sx] = True
                continue
            stack = [(sx, sy)]
            pixels: list[tuple[int, int]] = []
            min_x = max_x = sx
            min_y = max_y = sy
            while stack:
                x, y = stack.pop()
                if x < 0 or y < 0 or x >= w or y >= h or seen[y][x]:
                    continue
                seen[y][x] = True
                if not mask[y][x]:
                    continue
                pixels.append((x, y))
                min_x, max_x = min(min_x, x), max(max_x, x)
                min_y, max_y = min(min_y, y), max(max_y, y)
                stack.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
            if len(pixels) < min_area:
                continue
            bw, bh = max_x - min_x + 1, max_y - min_y + 1
            out.append({
                "x": min_x, "y": min_y, "w": bw, "h": bh,
                "area": len(pixels), "pixels": pixels,
                "fill_ratio": len(pixels) / float(bw * bh),
                "aspect": max(bw, bh) / float(min(bw, bh)),
            })
    return out


def detect_in_window(rgb: list[list[tuple[int, int, int]]],
                     hsv: list[list[tuple[int, int, int]]]) -> dict | None:
    """
    Find the dominant glyph in one window.

    ``rgb``/``hsv`` are row-major pixel grids for the same window. Returns the
    winning component's feature dict, or None when the window holds nothing
    salient (a label sitting on plain basemap).
    """
    if not rgb or not rgb[0]:
        return None
    h, w = len(rgb), len(rgb[0])
    n = h * w

    # Salience = chroma + deviation from the window's own median luminance.
    lum = [[0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2] for p in row] for row in rgb]
    med_lum = percentile([v for row in lum for v in row], 0.5)
    sal: list[list[float]] = []
    for y in range(h):
        srow = []
        for x in range(w):
            r, g, b = rgb[y][x]
            chroma = max(r, g, b) - min(r, g, b)
            srow.append(chroma + abs(lum[y][x] - med_lum))
        sal.append(srow)

    thr = max(SALIENCE_FLOOR, percentile([v for row in sal for v in row],
                                         SALIENCE_PERCENTILE))
    mask = [[sal[y][x] >= thr for x in range(w)] for y in range(h)]

    min_area = max(MIN_AREA_PX, int(n * MIN_AREA_FRAC))
    max_area = int(n * MAX_AREA_FRAC)
    comps = [c for c in connected_components(mask, min_area=min_area)
             if c["area"] <= max_area]
    if not comps:
        return None

    # Prefer the component that is both large and compact — a glyph, not a
    # streak of basemap texture.
    comp = max(comps, key=lambda c: c["area"] * (0.5 + 0.5 * c["fill_ratio"]))

    hues, sats, vals, weights = [], [], [], []
    for x, y in comp["pixels"]:
        hh, ss, vv = hsv[y][x]
        hues.append(hh * 360.0 / 255.0)
        sats.append(ss / 255.0)
        vals.append(vv / 255.0)
        weights.append(ss / 255.0)     # weight hue by saturation; grey has no hue

    # Hash the glyph's silhouette, not just the luminance inside its bounding
    # box: pixels in the box that are not part of the component are zeroed, so a
    # filled circle and a filled square of the same size hash differently. Using
    # raw luminance alone made every solid shape collapse to the same hash.
    member = set(comp["pixels"])
    gray_block = [
        [int(lum[y][x]) if (x, y) in member else 0
         for x in range(comp["x"], comp["x"] + comp["w"])]
        for y in range(comp["y"], comp["y"] + comp["h"])
    ]

    return {
        "x": comp["x"], "y": comp["y"], "w": comp["w"], "h": comp["h"],
        "area": comp["area"],
        "aspect": round(comp["aspect"], 3),
        "fill_ratio": round(comp["fill_ratio"], 3),
        "hue_deg": round(circular_mean_hue(hues, weights), 1),
        "saturation": round(sum(sats) / len(sats), 3),
        "value": round(sum(vals) / len(vals), 3),
        "ahash": average_hash(gray_block),
    }


# --- image plumbing ----------------------------------------------------------


def _grid(img, box: tuple[int, int, int, int]) -> list[list[tuple]]:
    """Row-major pixel grid for a crop box."""
    crop = img.crop(box)
    w, h = crop.size
    px = list(crop.getdata())
    return [px[y * w:(y + 1) * w] for y in range(h)]


def glyph_window(bx: int, by: int, bw: int, bh: int,
                 img_w: int, img_h: int) -> tuple[int, int, int, int] | None:
    """Search window left of and above a label box, clipped to the image."""
    unit = max(bh, 10)
    x0 = int(bx - unit * WIN_LEFT_MULT)
    x1 = int(bx + unit * WIN_RIGHT_MULT)
    y0 = int(by - unit * WIN_UP_MULT)
    y1 = int(by + bh + unit * WIN_DOWN_MULT)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img_w, x1), min(img_h, y1)
    if x1 - x0 < 6 or y1 - y0 < 6:
        return None
    return (x0, y0, x1, y1)


def detect_for_screenshot(conn: sqlite3.Connection, sid: int, rel_path: str,
                          run_id: int) -> dict:
    """Detect and store icons for every geometry-carrying pin on one screenshot."""
    pins = conn.execute(
        """SELECT pin_id, bbox_x, bbox_y, bbox_w, bbox_h
           FROM labeled_pins
           WHERE screenshot_id = ? AND bbox_x IS NOT NULL AND bbox_h IS NOT NULL
           ORDER BY pin_id LIMIT ?""",
        (sid, MAX_ICONS_PER_SCREENSHOT),
    ).fetchall()
    if not pins:
        return {"ok": True, "icons": 0, "reason": "no_geometry_pins"}

    full = REPO / rel_path
    if not full.exists():
        return {"ok": False, "icons": 0, "reason": "missing"}

    try:
        with Image.open(full) as im:
            im.load()
            im = ImageOps.exif_transpose(im)
            # Original RGB — deliberately not the binarized preprocessing the OCR
            # path uses, which would discard the colour the glyphs encode.
            rgb_img = im.convert("RGB")
            hsv_img = rgb_img.convert("HSV")
            img_w, img_h = rgb_img.size

            n = 0
            for pin_id, bx, by, bw, bh in pins:
                box = glyph_window(bx, by, bw, bh, img_w, img_h)
                if box is None:
                    continue
                feat = detect_in_window(_grid(rgb_img, box), _grid(hsv_img, box))
                if feat is None:
                    continue
                ax, ay = box[0] + feat["x"], box[1] + feat["y"]
                conn.execute(
                    """INSERT INTO icon_observations
                       (screenshot_id, pin_id, run_id, bbox_x, bbox_y, bbox_w, bbox_h,
                        centroid_x, centroid_y, area_px, aspect, fill_ratio,
                        hue_deg, saturation, value, ahash, confidence,
                        review_status, observed_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'unreviewed',?)""",
                    (sid, pin_id, run_id, ax, ay, feat["w"], feat["h"],
                     ax + feat["w"] // 2, ay + feat["h"] // 2,
                     feat["area"], feat["aspect"], feat["fill_ratio"],
                     feat["hue_deg"], feat["saturation"], feat["value"],
                     feat["ahash"], round(min(0.9, 0.4 + feat["fill_ratio"] / 2), 3),
                     _iso_now()),
                )
                n += 1
        conn.commit()
        return {"ok": True, "icons": n}
    except Exception as exc:
        return {"ok": False, "icons": 0, "reason": f"{type(exc).__name__}: {exc}"[:120]}


def run(budget_sec: float = 86400.0, limit: int = 0) -> dict:
    conn = sqlite3.connect(str(DB), timeout=30.0)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    ensure_schema(conn)

    sql = """SELECT DISTINCT s.screenshot_id, s.rel_path
             FROM screenshots s
             JOIN labeled_pins p ON p.screenshot_id = s.screenshot_id
             WHERE p.bbox_x IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM icon_observations i
                               WHERE i.screenshot_id = s.screenshot_id)
             ORDER BY s.screenshot_id"""
    if limit:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql).fetchall()
    if not rows:
        conn.close()
        return {"targets": 0, "icons": 0, "note": "no pins with geometry pending icons"}

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed) "
        "VALUES ('icon_detect', ?, 'in_progress', ?, 0, 0)",
        (_iso_now(), len(rows)),
    )
    run_id = cur.lastrowid
    conn.commit()

    t0 = time.time()
    n_ok = n_fail = n_icons = 0
    for i, (sid, rel_path) in enumerate(rows):
        if time.time() - t0 > budget_sec:
            print(f"[icons] budget {budget_sec}s reached; stopping", flush=True)
            break
        res = detect_for_screenshot(conn, sid, rel_path, run_id)
        if res.get("ok"):
            n_ok += 1
            n_icons += res.get("icons", 0)
        else:
            n_fail += 1
        if (i + 1) % 100 == 0:
            rate = (i + 1) / max(time.time() - t0, 1e-6)
            print(f"[icons] {i+1}/{len(rows)} ok={n_ok} fail={n_fail} "
                  f"icons={n_icons} rate={rate:.2f} img/s", flush=True)

    conn.execute(
        "UPDATE processing_runs SET ended_at=?, status='completed', n_processed=?, n_failed=?, notes=? "
        "WHERE run_id=?",
        (_iso_now(), n_ok, n_fail, json.dumps({"icons": n_icons}), run_id),
    )
    conn.commit()
    conn.close()
    return {"run_id": run_id, "targets": len(rows), "processed": n_ok,
            "failed": n_fail, "icons": n_icons,
            "elapsed_sec": round(time.time() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Detect FR24 map icons beside labeled pins.")
    ap.add_argument("--budget-sec", type=float, default=86400.0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    print(json.dumps(run(args.budget_sec, args.limit), indent=2))


if __name__ == "__main__":
    main()
