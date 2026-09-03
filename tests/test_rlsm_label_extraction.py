"""
Accuracy tests for RLSM label + icon extraction.

tests/test_rlsm_pipeline.py checks table shape and FK integrity against a
populated DB; nothing exercised the extraction logic itself, which is how a
docstring claiming "279 municipalities" against an actual 77 survived, and how
the Tier-2 double-emit and the MAYAGÜEZ fold bug went unnoticed.

These tests run on an in-memory SQLite DB built from the canonical schema and
need no tesseract, no Pillow and no corpus, so they run in CI.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from fr24.rlsm_extractors import extract_labeled_pins, scan_words_for_pois  # noqa: E402
from fr24.rlsm_gazetteer import load_gazetteer, tokenize  # noqa: E402
from fr24.rlsm_icons import (  # noqa: E402
    average_hash,
    circular_mean_hue,
    connected_components,
    detect_in_window,
    glyph_window,
    percentile,
    search_sides,
)
from fr24.rlsm_pipeline import _orientation_breakdown  # noqa: E402
from fr24.rlsm_wordboxes import load_words, union_box, words_from_tesseract_data  # noqa: E402
from fr24.rlsm_zones import ORIENTATION_SQL, orientation_for, zones_for  # noqa: E402

SCHEMA = REPO / "data" / "rlsm" / "schema.sql"


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

def _word(text: str, x: int, y: int, conf: float = 88.0) -> dict:
    return {"t": text, "x": x, "y": y, "w": len(text) * 14, "h": 26, "c": conf}


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA.read_text())
    c.execute("INSERT INTO processing_runs (run_kind, started_at, status, "
              "n_inputs, n_processed, n_failed) VALUES ('test', '2026-01-01', 'ok', 0, 0, 0)")
    yield c
    c.close()


# iPhone FR24 frame sizes, both ways up.
PORTRAIT_WH = (1170, 2532)
LANDSCAPE_WH = (2532, 1170)


def _add_screenshot(c: sqlite3.Connection, tag: str,
                    size: tuple[int, int] = PORTRAIT_WH) -> int:
    width, height = size
    c.execute(
        "INSERT INTO screenshots (sha256, filename, rel_path, ext, size_bytes, "
        "width, height, ingest_status, ocr_status, ingested_at) "
        "VALUES (?,?,?,'png',1024,?,?,'ok','ok','2026-01-01')",
        (f"sha-{tag}", f"{tag}.png", f"data/FR24_baseline/{tag}.png", width, height),
    )
    return int(c.execute("SELECT last_insert_rowid()").fetchone()[0])


def _add_observation(c: sqlite3.Connection, sid: int, zone: str, words: list) -> None:
    c.execute(
        "INSERT INTO ocr_observations (screenshot_id, zone, raw_text, "
        "raw_lines_json, confidence_mean, ocr_status, observed_at) "
        "VALUES (?,?,?,?,?,'ok','2026-01-01')",
        (sid, zone, " ".join(w["t"] for w in words), json.dumps(words),
         sum(w["c"] for w in words) / max(1, len(words))),
    )


def _pins(c: sqlite3.Connection, sid: int) -> list:
    return c.execute(
        "SELECT raw_label, pin_type_guess, confidence, bbox_x, bbox_y, "
        "centroid_x, centroid_y FROM labeled_pins WHERE screenshot_id=? "
        "ORDER BY confidence DESC", (sid,)).fetchall()


# --------------------------------------------------------------------------- #
# gazetteer
# --------------------------------------------------------------------------- #

def test_gazetteer_loads_the_full_gnis_extract():
    """The old inline vocabulary held 91 names. Guards against a silent loader
    failure that would quietly fall back to near-nothing."""
    stats = load_gazetteer().stats()
    assert stats["keys"] > 4000, f"gazetteer collapsed to {stats['keys']} keys"
    assert stats["canonical_names"] > 3000
    assert stats["by_tier"]["high"] > 2000


def test_umlaut_folds_so_mayaguez_matches_either_spelling():
    """Tesseract usually reads MAYAGÜEZ as MAYAGUEZ. The old _ascii_fold covered
    á-ú-ñ but not ü, so the key stayed MAYAGÜEZ and every real read missed
    Tier 1 and was logged as an unknown."""
    gaz = load_gazetteer()
    with_umlaut = gaz.lookup("MAYAGÜEZ")
    without = gaz.lookup("MAYAGUEZ")
    assert with_umlaut is not None and without is not None
    assert with_umlaut["canonical"] == without["canonical"]


@pytest.mark.parametrize("label", [
    "Bayamón", "Bayamon", "Cataño", "Catano", "Loíza", "Loiza",
    "Añasco", "Anasco", "Comerío", "Comerio",
])
def test_accented_municipios_resolve_either_way(label):
    assert load_gazetteer().lookup(label) is not None, f"{label} did not resolve"


def test_matching_respects_word_boundaries():
    """The old scan was `if key in text_upper`, so the GNIS feature class 'Sea'
    matched inside 'SEAWORLD'. Matching is now over token n-grams."""
    gaz = load_gazetteer()
    tokens, _ = tokenize(["SEAWORLD"])
    assert gaz.match_tokens(tokens) == []


def test_ambiguous_single_tokens_need_a_longer_gram():
    """'Sabana' alone is a generic Spanish word that happens to be a GNIS
    populated place; 'Sabana Grande' is a municipio."""
    gaz = load_gazetteer()
    alone, _ = tokenize(["Sabana"])
    assert gaz.match_tokens(alone) == []
    pair, _ = tokenize(["Sabana", "Grande"])
    assert [e["canonical"] for _, _, e in gaz.match_tokens(pair)] == ["Sabana Grande Municipio"]


def test_sub_municipio_features_are_reachable():
    """The whole point of loading GNIS: features below municipio resolution that
    the 91-name list could never see."""
    gaz = load_gazetteer()
    for name in ("El Yunque", "Cordillera Central", "Bahía de San Juan",
                 "Isla Desecheo", "Caño de Martín Peña"):
        assert gaz.lookup(name) is not None, f"{name} missing from gazetteer"


def test_municipio_wins_a_collapsed_key_over_its_barrio():
    """'Florida Municipio', 'Florida Barrio' and 'Florida Zona Urbana' all
    collapse to 'florida'; an FR24 map label means the municipio."""
    assert load_gazetteer().lookup("Florida")["canonical"] == "Florida Municipio"


# --------------------------------------------------------------------------- #
# tiering / confidence
# --------------------------------------------------------------------------- #

def test_confidence_is_not_a_constant():
    """Confidence used to be min(0.90, 0.70) — literally 0.70 for every
    vocabulary hit, with no per-type or per-match-quality signal."""
    hits = scan_words_for_pois([
        _word("Bayamon", 100, 200),      # populated place, high tier
        _word("Yunque", 100, 300),       # summit, geo tier
        _word("Zorbatron", 100, 400),    # no entry, Tier 2
    ])
    by_label = {h["label"]: h["confidence"] for h in hits}
    muni = by_label["Bayamón Municipio"]
    unknown = next(v for k, v in by_label.items() if "Zorbatron" in k)
    assert muni > unknown
    assert len({round(v, 3) for v in by_label.values()}) > 1


def test_low_ocr_confidence_lowers_pin_confidence():
    clean = scan_words_for_pois([_word("Bayamon", 10, 10, conf=95.0)])[0]
    noisy = scan_words_for_pois([_word("Bayamon", 10, 10, conf=35.0)])[0]
    assert noisy["confidence"] < clean["confidence"]


def test_lower_zone_weight_reduces_confidence():
    """Labels recovered from the aircraft_card zone are real but come from a
    weaker source (PSM 6 on a card crop), so they must not outrank the map."""
    primary = scan_words_for_pois([_word("Ponce", 10, 10)], zone_weight=1.0)[0]
    secondary = scan_words_for_pois([_word("Ponce", 10, 10)], zone_weight=0.8)[0]
    assert secondary["confidence"] < primary["confidence"]


# --------------------------------------------------------------------------- #
# Tier-2 suppression — the review-queue regression
# --------------------------------------------------------------------------- #

def test_tier1_hits_are_not_re_emitted_as_unknowns(conn):
    """The regression this suite exists for.

    `matched_spans` was computed and never used, so every Tier-1 hit was also
    caught by the capitalized-word-group regex. "FLORIDA Bayamon" produced three
    rows — Bayamón, Florida, and junk "FLORIDA Bayamon" at confidence 0.25 —
    and the junk row sat under the 0.5 threshold, so it landed in
    manual_review_queue. A meaningful share of the backlog was self-inflicted.
    """
    sid = _add_screenshot(conn, "double-emit")
    _add_observation(conn, sid, "label_layer",
                     [_word("FLORIDA", 200, 400), _word("Bayamon", 300, 500)])

    extract_labeled_pins(conn, run_id=1)

    rows = _pins(conn, sid)
    assert len(rows) == 2, f"expected 2 pins, got {[r[0] for r in rows]}"
    assert {r[0] for r in rows} == {"Florida Municipio", "Bayamón Municipio"}
    assert all(r[1] != "unknown" for r in rows)
    assert all(r[2] >= 0.5 for r in rows), "a Tier-1 hit fell under review threshold"


def test_ui_chrome_never_becomes_an_unknown_candidate(conn):
    """Tesseract turns FR24's glyphs into junk like '®fli htradar24 ©', which the
    old Tier-2 regex promoted into unknown_label_candidate review rows."""
    sid = _add_screenshot(conn, "chrome")
    _add_observation(conn, sid, "label_layer", [
        _word("®fli", 10, 100), _word("htradar24", 60, 100),
        _word("Route", 10, 140), _word("Follow", 90, 140),
        _word("Bayamon", 300, 500),
    ])

    extract_labeled_pins(conn, run_id=1)

    labels = {r[0] for r in _pins(conn, sid)}
    assert labels == {"Bayamón Municipio"}, f"chrome leaked through: {labels}"


def test_genuine_unknowns_are_still_captured(conn):
    """Suppression must not silence real unrecognised labels — those are the
    signal for extending the gazetteer."""
    sid = _add_screenshot(conn, "unknown")
    _add_observation(conn, sid, "label_layer",
                     [_word("Bayamon", 100, 100), _word("Zorbatron", 400, 700)])

    extract_labeled_pins(conn, run_id=1)

    rows = _pins(conn, sid)
    assert any(r[1] == "unknown" and "Zorbatron" in r[0] for r in rows)


# --------------------------------------------------------------------------- #
# geometry — what the affine geocoder needs
# --------------------------------------------------------------------------- #

def test_pins_carry_real_pixel_geometry(conn):
    """bbox_* and centroid_* used to be inserted as six literal None values, so a
    "labeled pin" was a name with no position on the frame — and the
    per-screenshot affine geocoder needs two located pins to fit."""
    sid = _add_screenshot(conn, "geometry")
    _add_observation(conn, sid, "label_layer",
                     [_word("Bayamon", 300, 500), _word("Ponce", 700, 1100)])

    extract_labeled_pins(conn, run_id=1)

    rows = _pins(conn, sid)
    assert len(rows) == 2
    for label, _type, _conf, bx, by, cx, cy in rows:
        assert bx is not None and by is not None, f"{label} has no bbox"
        assert cx is not None and cy is not None, f"{label} has no centroid"
        assert 0 < cx < 1170 and 0 < cy < 2532

    fittable = conn.execute(
        "SELECT COUNT(*) FROM (SELECT screenshot_id FROM labeled_pins "
        "WHERE centroid_x IS NOT NULL GROUP BY screenshot_id HAVING COUNT(*) >= 2)"
    ).fetchone()[0]
    assert fittable == 1


def test_multi_word_label_geometry_spans_all_its_words(conn):
    sid = _add_screenshot(conn, "multiword")
    _add_observation(conn, sid, "label_layer",
                     [_word("San", 100, 400), _word("Juan", 160, 400)])

    extract_labeled_pins(conn, run_id=1)

    (label, _t, _c, bx, _by, cx, _cy), = _pins(conn, sid)
    assert label == "San Juan Municipio"
    assert bx == 100
    assert cx > 100, "centroid should sit between the two words, not on the first"


def test_bottom_of_frame_labels_are_read_from_the_card_zone(conn):
    """The label_layer zone stops at 65% of frame height, so any map label below
    it was discarded. aircraft_card is already OCR'd, so reading its words costs
    nothing and closes that gap."""
    sid = _add_screenshot(conn, "bottom")
    _add_observation(conn, sid, "aircraft_card", [_word("Ponce", 100, 1800)])

    extract_labeled_pins(conn, run_id=1)

    rows = _pins(conn, sid)
    assert [r[0] for r in rows] == ["Ponce Municipio"]
    assert rows[0][6] > 1600, "geometry should be in the lower frame"


def test_screenshots_without_word_boxes_are_skipped_not_faked(conn):
    """A pre-word-box observation must not produce a geometry-less pin; it is
    counted so the runner can report the --reocr-boxes backfill."""
    sid = _add_screenshot(conn, "legacy")
    conn.execute(
        "INSERT INTO ocr_observations (screenshot_id, zone, raw_text, "
        "raw_lines_json, confidence_mean, ocr_status, observed_at) "
        "VALUES (?, 'label_layer', 'SAN JUAN', '[]', 80, 'ok', '2026-01-01')", (sid,))

    result = extract_labeled_pins(conn, run_id=1)

    assert _pins(conn, sid) == []
    assert result["skipped_no_word_boxes"] == 1


def test_newest_observation_per_zone_wins(conn):
    """Raw OCR is append-only, so a screenshot can hold rows from the legacy
    6-zone run, the 3-zone run and a --reocr-boxes pass. Concatenating them all
    would double-count."""
    sid = _add_screenshot(conn, "reocr")
    _add_observation(conn, sid, "label_layer", [_word("Bayamon", 300, 500)])
    _add_observation(conn, sid, "label_layer", [_word("Ponce", 700, 900)])

    extract_labeled_pins(conn, run_id=1)

    assert [r[0] for r in _pins(conn, sid)] == ["Ponce Municipio"]


def test_extraction_is_idempotent(conn):
    sid = _add_screenshot(conn, "idem")
    _add_observation(conn, sid, "label_layer", [_word("Bayamon", 300, 500)])

    extract_labeled_pins(conn, run_id=1)
    first = _pins(conn, sid)
    extract_labeled_pins(conn, run_id=1)

    assert _pins(conn, sid) == first


# --------------------------------------------------------------------------- #
# word boxes
# --------------------------------------------------------------------------- #

def test_word_boxes_are_translated_into_full_image_coordinates():
    """Boxes come out of a crop; the zone origin is added at write time so
    consumers never need to know which zone a word came from."""
    data = {"text": ["Ponce", "x", ""], "conf": [92, 95, -1],
            "left": [10, 0, 0], "top": [20, 0, 0],
            "width": [70, 5, 0], "height": [26, 5, 0]}
    boxes = words_from_tesseract_data(data, x_off=0, y_off=126)
    assert len(boxes) == 1, "single-char and empty words should be dropped"
    assert boxes[0]["t"] == "Ponce"
    assert boxes[0]["y"] == 146


def test_low_confidence_words_are_dropped():
    data = {"text": ["Ponce", "rubbish"], "conf": [92, 11],
            "left": [0, 0], "top": [0, 0], "width": [70, 70], "height": [26, 26]}
    assert [b["t"] for b in words_from_tesseract_data(data)] == ["Ponce"]


@pytest.mark.parametrize("value", [None, "", "[]", "not json", '{"a": 1}'])
def test_load_words_tolerates_legacy_and_malformed_values(value):
    assert load_words(value) == []


def test_union_box_spans_every_word():
    assert union_box([_word("aa", 10, 10), _word("bb", 100, 40)]) == (10, 10, 118, 56)


# --------------------------------------------------------------------------- #
# icons
# --------------------------------------------------------------------------- #

def _synthetic_window(shape: str, hue_deg: float = 30.0, size: int = 40):
    """Grey basemap with a saturated glyph, as (rgb_grid, hsv_grid)."""
    import colorsys
    bg = (120, 120, 122)
    r, g, b = colorsys.hsv_to_rgb(hue_deg / 360.0, 0.95, 0.95)
    fg = (int(r * 255), int(g * 255), int(b * 255))
    c, rad = size // 2, 7
    rgb = []
    for y in range(size):
        row = []
        for x in range(size):
            if shape == "square":
                inside = abs(x - c) <= rad and abs(y - c) <= rad
            elif shape == "circle":
                inside = (x - c) ** 2 + (y - c) ** 2 <= rad * rad
            else:  # cross
                inside = ((abs(x - c) <= 2 and abs(y - c) <= rad)
                          or (abs(y - c) <= 2 and abs(x - c) <= rad))
            row.append(fg if inside else bg)
        rgb.append(row)
    hsv = [[tuple(int(v * 255) for v in colorsys.rgb_to_hsv(*(ch / 255 for ch in px)))
            for px in row] for row in rgb]
    return rgb, hsv


def test_hue_average_is_circular():
    """The arithmetic mean of 350° and 10° is 180° (cyan) when the answer is red."""
    assert circular_mean_hue([350.0, 10.0]) == pytest.approx(0.0, abs=0.01)


def test_percentile_interpolates():
    assert percentile([1, 2, 3, 4, 5], 0.5) == pytest.approx(3.0)
    assert percentile([], 0.5) == 0.0


def test_connected_components_separates_disjoint_blobs():
    mask = [[False] * 10 for _ in range(10)]
    for y in range(1, 4):
        for x in range(1, 4):
            mask[y][x] = True
    for y in range(6, 9):
        for x in range(6, 9):
            mask[y][x] = True
    comps = connected_components(mask, min_area=1)
    assert len(comps) == 2
    assert all(c["area"] == 9 for c in comps)


def test_icon_fingerprint_is_deterministic():
    a = detect_in_window(*_synthetic_window("circle"))
    b = detect_in_window(*_synthetic_window("circle"))
    assert a["ahash"] == b["ahash"]
    assert a["hue_deg"] == b["hue_deg"]


def test_different_glyph_shapes_hash_differently():
    """Hashing raw luminance inside the component's own bbox made every solid
    shape collapse to the same value; the silhouette is masked in instead."""
    hashes = {s: detect_in_window(*_synthetic_window(s))["ahash"]
              for s in ("square", "circle", "cross")}
    assert len(set(hashes.values())) == 3, hashes


def test_colour_is_captured_and_shape_hash_is_colour_invariant():
    """Icons are cropped from the original RGB precisely so colour survives:
    same silhouette, different colour must share a hash but differ in hue."""
    orange = detect_in_window(*_synthetic_window("circle", hue_deg=30.0))
    blue = detect_in_window(*_synthetic_window("circle", hue_deg=210.0))
    assert orange["ahash"] == blue["ahash"]
    assert abs(orange["hue_deg"] - blue["hue_deg"]) > 100
    assert orange["saturation"] > 0.5 and blue["saturation"] > 0.5


def test_featureless_window_yields_no_icon():
    """A label sitting on plain basemap must not invent a glyph."""
    size = 40
    rgb = [[(120, 120, 122)] * size for _ in range(size)]
    hsv = [[(0, 0, 120)] * size for _ in range(size)]
    assert detect_in_window(rgb, hsv) is None


def test_average_hash_is_64_bits():
    h = average_hash([[i * 4 for i in range(16)] for _ in range(16)])
    assert len(h) == 16
    int(h, 16)


def test_glyph_window_sits_left_of_and_above_the_label():
    box = glyph_window(bx=300, by=500, bw=98, bh=26, img_w=1170, img_h=2532)
    x0, y0, x1, y1 = box
    assert x0 < 300 and y0 < 500
    assert x1 <= 300 + 26, "window should not extend far into the label text"


def test_glyph_window_is_clipped_to_the_image():
    box = glyph_window(bx=2, by=2, bw=40, bh=26, img_w=1170, img_h=2532)
    if box is not None:
        assert box[0] >= 0 and box[1] >= 0


# --------------------------------------------------------------------------- #
# portrait / landscape compatibility
# --------------------------------------------------------------------------- #

def test_orientation_is_derived_from_aspect():
    assert orientation_for(*PORTRAIT_WH) == "portrait"
    assert orientation_for(*LANDSCAPE_WH) == "landscape"
    assert orientation_for(1000, 1000) == "portrait", "square counts as portrait"


def test_sql_orientation_matches_the_python_rule(conn):
    """The report groups by orientation in SQL. That second definition must not
    drift from orientation_for()."""
    sizes = [PORTRAIT_WH, LANDSCAPE_WH, (1000, 1000), (2532, 1170), (828, 1792)]
    for i, size in enumerate(sizes):
        _add_screenshot(conn, f"orient-{i}", size=size)
    rows = conn.execute(
        f"SELECT s.width, s.height, {ORIENTATION_SQL.format(t='s')} FROM screenshots s"
    ).fetchall()
    assert rows
    for width, height, sql_answer in rows:
        assert sql_answer == orientation_for(width, height), (width, height)


@pytest.mark.parametrize("size", [PORTRAIT_WH, LANDSCAPE_WH])
def test_both_orientations_expose_the_same_zone_names(size):
    """Everything downstream keys on zone name, not geometry — the extractor's
    confidence weights, the word-box offsets, the review queue."""
    names = {z.name for z in zones_for(*size)}
    assert names == {"status_bar", "label_layer", "aircraft_card"}


@pytest.mark.parametrize("size", [PORTRAIT_WH, LANDSCAPE_WH])
def test_zones_stay_inside_the_frame(size):
    width, height = size
    for z in zones_for(width, height):
        assert z.x >= 0 and z.y >= 0
        assert z.x + z.w <= width and z.y + z.h <= height
        assert z.w > 0 and z.h > 0


def test_landscape_card_zone_is_offset_in_x_not_y():
    """In landscape the aircraft card is a right-hand strip, so its word boxes
    need a non-zero x offset — the portrait path only ever needed y."""
    card = next(z for z in zones_for(*LANDSCAPE_WH) if z.name == "aircraft_card")
    assert card.x > 0, "landscape card must be offset horizontally"
    portrait_card = next(z for z in zones_for(*PORTRAIT_WH) if z.name == "aircraft_card")
    assert portrait_card.x == 0 and portrait_card.y > 0


def test_word_boxes_land_in_frame_coordinates_for_a_landscape_card():
    """Regression guard for the offset that only matters in landscape: a word
    read from the card strip must come back at its true frame x, not at the
    crop-relative x."""
    card = next(z for z in zones_for(*LANDSCAPE_WH) if z.name == "aircraft_card")
    data = {"text": ["Ponce"], "conf": [92], "left": [10], "top": [20],
            "width": [70], "height": [26]}
    (box,) = words_from_tesseract_data(data, x_off=card.x, y_off=card.y)
    assert box["x"] == card.x + 10
    assert box["y"] == card.y + 20
    assert box["x"] > LANDSCAPE_WH[0] // 2, "card sits in the right half of the frame"


@pytest.mark.parametrize("size", [PORTRAIT_WH, LANDSCAPE_WH])
def test_pins_extract_with_geometry_in_either_orientation(conn, size):
    orientation = orientation_for(*size)
    sid = _add_screenshot(conn, f"e2e-{orientation}", size=size)
    _add_observation(conn, sid, "label_layer",
                     [_word("Bayamon", 300, 400), _word("Ponce", 700, 800)])

    extract_labeled_pins(conn, run_id=1)

    rows = _pins(conn, sid)
    assert len(rows) == 2
    for label, _t, _c, _bx, _by, cx, cy in rows:
        assert cx is not None and cy is not None, f"{label} has no centroid"
        assert 0 < cx < size[0] and 0 < cy < size[1], f"{label} outside the frame"


def test_label_at_the_left_edge_searches_right_for_its_glyph():
    """A label pinned against the frame edge has no neighbourhood on its default
    side. Returning nothing there is indistinguishable from 'no icon here', which
    is what made the left-only search look orientation-specific."""
    assert search_sides(bx=4, bw=90, bh=26, img_w=2532)[0] == "right"


def test_interior_labels_still_prefer_the_left():
    assert search_sides(bx=800, bw=90, bh=26, img_w=2532)[0] == "left"


def test_label_at_the_right_edge_does_not_try_the_right():
    sides = search_sides(bx=2480, bw=48, bh=26, img_w=2532)
    assert "right" not in sides


def test_a_window_clipped_to_a_sliver_is_rejected():
    """A label hard against the frame edge clips its left window down to the
    sliver overlapping its own text. Detecting in that sliver fingerprints the
    label as an icon — a confident false positive that would pollute the hash
    clusters — so the window must be refused instead."""
    assert glyph_window(bx=2, by=400, bw=140, bh=26, img_w=2532, img_h=1170,
                        side="left") is None
    assert glyph_window(bx=2, by=400, bw=140, bh=26, img_w=2532, img_h=1170,
                        side="right") is not None


@pytest.mark.parametrize("size", [PORTRAIT_WH, LANDSCAPE_WH])
def test_a_right_side_window_is_usable_at_the_left_edge(size):
    width, height = size
    left = glyph_window(bx=4, by=300, bw=90, bh=26, img_w=width, img_h=height,
                        side="left")
    right = glyph_window(bx=4, by=300, bw=90, bh=26, img_w=width, img_h=height,
                         side="right")
    assert right is not None, "right-side fallback must produce a window"
    assert right[2] <= width and right[3] <= height
    if left is not None:
        assert right[0] >= left[0], "right window should sit further right"


@pytest.mark.parametrize("size", [PORTRAIT_WH, LANDSCAPE_WH])
def test_glyph_windows_stay_inside_the_frame_on_every_side(size):
    width, height = size
    for side in ("left", "right"):
        for bx, by in ((0, 0), (width - 60, height - 40), (width // 2, height // 2)):
            box = glyph_window(bx, by, 60, 26, width, height, side=side)
            if box is None:
                continue
            x0, y0, x1, y1 = box
            assert 0 <= x0 < x1 <= width
            assert 0 <= y0 < y1 <= height


def test_orientation_breakdown_separates_the_two_layouts(conn):
    """The measurement that makes landscape checkable: a regression in one
    orientation is invisible in an average the other dominates."""
    p = _add_screenshot(conn, "brk-p", size=PORTRAIT_WH)
    ls = _add_screenshot(conn, "brk-l", size=LANDSCAPE_WH)
    for sid in (p, ls):
        _add_observation(conn, sid, "label_layer", [_word("Bayamon", 300, 400)])
    extract_labeled_pins(conn, run_id=1)

    breakdown = _orientation_breakdown(conn)

    assert set(breakdown) == {"portrait", "landscape"}
    for entry in breakdown.values():
        assert entry["screenshots"] == 1
        assert entry["pins"] == 1
        assert entry["pins_located"] == 1
