"""Tests for strategy #4 — fr24/track_vectorizer.py + CV-first rlsm_flight_track.

Synthetic screenshots are PIL-drawn in FR24 trail orange on a dark map
background: a straight line ('linear'), a circle ('orbit'), an elongated
ellipse ('loop'), and two collinear segments (has_gap). The integration test
proves rlsm_flight_track.run() uses the CV pass when images exist under
--image-root and falls back to the 0.3-confidence heuristic when they don't.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from fr24.route_extractor import RouteExtractor  # noqa: E402
from fr24.track_vectorizer import (  # noqa: E402
    CV_CONFIDENCE,
    vectorize_candidates,
    vectorize_image,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = REPO_ROOT / "data" / "rlsm" / "schema.sql"

ORANGE = (230, 130, 40)      # inside route_extractor's 'orange' band
BACKGROUND = (30, 32, 36)    # dark map — matches no color band


def _image(draw_fn, size=(400, 400)) -> Image.Image:
    img = Image.new("RGB", size, BACKGROUND)
    draw_fn(ImageDraw.Draw(img))
    return img


def _extract(img: Image.Image):
    import numpy as np
    return RouteExtractor().extract_array(np.array(img, dtype=np.uint8))


# Geometry stays inside the FR24UISegmenter geometric map bbox for 400x400
# images (x 16..384, y 32..288) so the CV-first integration test sees the
# whole shape after the map crop.
LINE = lambda d: d.line((50, 200, 350, 200), fill=ORANGE, width=3)          # noqa: E731
CIRCLE = lambda d: d.ellipse((120, 90, 280, 250), outline=ORANGE, width=3)  # noqa: E731
ELLIPSE = lambda d: d.ellipse((50, 150, 350, 250), outline=ORANGE, width=3) # noqa: E731


def GAP(d):
    d.line((50, 200, 150, 200), fill=ORANGE, width=3)
    d.line((250, 200, 350, 200), fill=ORANGE, width=3)


def test_straight_line_is_linear():
    features = vectorize_candidates(_extract(_image(LINE)))
    assert features is not None
    assert features.path_shape == "linear"
    assert features.has_loop == 0 and features.has_orbit == 0 and features.has_gap == 0
    assert features.confidence == CV_CONFIDENCE
    assert 250 <= features.track_length_px <= 350
    x, y, w, h = features.bbox
    assert w > 250 and h < 20


def test_circle_is_orbit():
    features = vectorize_candidates(_extract(_image(CIRCLE)))
    assert features is not None
    assert features.path_shape == "orbit"
    assert features.has_orbit == 1 and features.has_loop == 1
    # circumference of a ~80 px-radius ring
    assert 400 <= features.track_length_px <= 650


def test_elongated_ellipse_is_loop_not_orbit():
    features = vectorize_candidates(_extract(_image(ELLIPSE)))
    assert features is not None
    assert features.path_shape == "loop"
    assert features.has_loop == 1 and features.has_orbit == 0


def test_broken_trail_sets_has_gap():
    features = vectorize_candidates(_extract(_image(GAP)))
    assert features is not None
    assert features.has_gap == 1
    assert features.component_count == 2
    assert features.path_shape == "linear"
    x, y, w, h = features.bbox  # union spans both segments
    assert w > 250


def test_empty_or_offband_image_yields_none():
    assert vectorize_candidates(_extract(_image(lambda d: None))) is None
    blue_line = _image(lambda d: d.line((50, 200, 350, 200), fill=(40, 140, 220), width=3))
    assert vectorize_candidates(_extract(blue_line)) is None


def test_vectorize_image_reads_file(tmp_path):
    path = tmp_path / "line.png"
    _image(LINE).save(path)
    features = vectorize_image(str(path), extractor=RouteExtractor())
    assert features is not None and features.path_shape == "linear"
    assert vectorize_image(str(tmp_path / "missing.png"),
                           extractor=RouteExtractor()) is None


# ──────────────────────────────────────────────────────────────────────────
# rlsm_flight_track integration: CV first, heuristic fallback
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cv_rlsm_db(tmp_path: Path, monkeypatch):
    if not SCHEMA_SQL.exists():
        pytest.skip("data/rlsm/schema.sql not tracked")
    corpus = tmp_path / "corpus"
    (corpus / "2026-06").mkdir(parents=True)
    _image(CIRCLE).save(corpus / "2026-06" / "orbit.png")
    _image(LINE).save(corpus / "2026-06" / "line.png")
    # screenshot 3 has a rel_path but NO file on disk -> heuristic fallback

    db = tmp_path / "rlsm.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript(SCHEMA_SQL.read_text())
    rows = [
        (1, "orbit.png", "2026-06/orbit.png"),
        (2, "line.png", "2026-06/line.png"),
        (3, "missing.png", "2026-06/missing.png"),
    ]
    for sid, filename, rel_path in rows:
        conn.execute(
            "INSERT INTO screenshots (screenshot_id, sha256, filename, rel_path, ext,"
            " size_bytes, width, height, ingest_status, ingested_at)"
            " VALUES (?, ?, ?, ?, 'png', 1000, 400, 400, 'ok', '2026-06-01T00:00:00Z')",
            (sid, f"sha{sid}" * 16, filename, rel_path),
        )
    # screenshot 3 gets a linear speed/heading signal for the heuristic
    conn.execute(
        "INSERT INTO aircraft_observations (screenshot_id, registration, identity_status,"
        " speed_kt, heading_deg, source_zone, observed_at)"
        " VALUES (3, 'N3EF', 'confirmed', 120, 180, 'aircraft_card', '2026-06-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    import fr24.rlsm_flight_track as ft
    monkeypatch.setattr(ft, "DB", db)
    return db, corpus


def test_run_uses_cv_when_image_exists_and_falls_back_otherwise(cv_rlsm_db):
    from fr24.rlsm_flight_track import HEURISTIC_CONFIDENCE, run

    db, corpus = cv_rlsm_db
    snapshot = run(budget_sec=30.0, image_root=corpus)
    assert snapshot["processed"] == 3
    assert snapshot["cv_classified"] == 2

    conn = sqlite3.connect(str(db))
    rows = {
        sid: (shape, loop, orbit, gap, length, conf)
        for sid, shape, loop, orbit, gap, length, conf in conn.execute(
            "SELECT screenshot_id, path_shape, has_loop, has_orbit, has_gap,"
            " track_length_px, confidence FROM flight_track_features"
        )
    }
    conn.close()

    orbit_row = rows[1]
    assert orbit_row[0] == "orbit" and orbit_row[2] == 1
    assert orbit_row[4] is not None and orbit_row[4] > 0
    assert orbit_row[5] == CV_CONFIDENCE

    line_row = rows[2]
    assert line_row[0] == "linear" and line_row[5] == CV_CONFIDENCE

    fallback_row = rows[3]
    assert fallback_row[0] == "linear"          # heuristic classification
    assert fallback_row[5] == HEURISTIC_CONFIDENCE
    assert fallback_row[4] is None              # no pixel data -> NULL length


def test_run_without_image_root_is_pure_heuristic(cv_rlsm_db):
    from fr24.rlsm_flight_track import HEURISTIC_CONFIDENCE, run

    db, _ = cv_rlsm_db
    snapshot = run(budget_sec=30.0)
    assert snapshot["cv_classified"] == 0
    conn = sqlite3.connect(str(db))
    confidences = [c for (c,) in conn.execute(
        "SELECT confidence FROM flight_track_features"
    )]
    conn.close()
    assert confidences and all(c == HEURISTIC_CONFIDENCE for c in confidences)
