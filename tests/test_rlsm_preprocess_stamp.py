"""
The preprocess stamp, and the staleness it makes visible.

Resume keys on ``screenshots.ocr_status``, so a screenshot already marked
``ok`` is never re-read. Before this stamp existed, nothing in the database
said which preprocessing produced a row — so changing a zone's mode or scale
left older rows in place, worse than the new ones, and invisible.
"""
from __future__ import annotations

import sqlite3

import pytest

from fr24.rlsm_preprocess import config_stamp, ensure_observation_columns

OLD_SHAPE = """
CREATE TABLE ocr_observations (
    obs_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id    INTEGER NOT NULL,
    zone             TEXT NOT NULL,
    raw_text         TEXT NOT NULL,
    engine_version   TEXT,
    psm              INTEGER,
    ocr_status       TEXT NOT NULL,
    observed_at      TEXT NOT NULL
);
"""

STALE_SQL = """
SELECT COUNT(*) FROM ocr_observations o
WHERE o.obs_id IN (SELECT MAX(obs_id) FROM ocr_observations
                   WHERE zone='label_layer' GROUP BY screenshot_id)
  AND (o.preprocess IS NULL OR o.preprocess <> ?
       OR o.preprocess_scale IS NULL
       OR ABS(o.preprocess_scale - ?) > 1e-6)
"""


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(OLD_SHAPE)
    return c


def _row(c, sid, mode=None, scale=None, zone="label_layer"):
    cols = "screenshot_id, zone, raw_text, ocr_status, observed_at"
    vals = [sid, zone, "x", "ok", "2026-07-28T00:00:00Z"]
    have = {r[1] for r in c.execute("PRAGMA table_info(ocr_observations)")}
    if "preprocess" in have:
        cols += ", preprocess, preprocess_scale"
        vals += [mode, scale]
    c.execute(f"INSERT INTO ocr_observations ({cols}) "
              f"VALUES ({','.join('?' * len(vals))})", vals)
    c.commit()


class TestMigration:
    def test_adds_both_columns(self, conn):
        assert ensure_observation_columns(conn) == ["preprocess", "preprocess_scale"]
        cols = {r[1] for r in conn.execute("PRAGMA table_info(ocr_observations)")}
        assert {"preprocess", "preprocess_scale"} <= cols

    def test_is_idempotent(self, conn):
        ensure_observation_columns(conn)
        assert ensure_observation_columns(conn) == []

    def test_existing_rows_survive_and_read_as_unknown(self, conn):
        _row(conn, 1)
        ensure_observation_columns(conn)
        got = conn.execute("SELECT preprocess, preprocess_scale "
                           "FROM ocr_observations").fetchone()
        assert got == (None, None)


class TestStalenessQuery:
    def test_unstamped_rows_are_stale(self, conn):
        _row(conn, 1)
        ensure_observation_columns(conn)
        assert conn.execute(STALE_SQL, ("label_mask", 2.0)).fetchone()[0] == 1

    def test_matching_stamp_is_not_stale(self, conn):
        ensure_observation_columns(conn)
        _row(conn, 1, "label_mask", 2.0)
        assert conn.execute(STALE_SQL, ("label_mask", 2.0)).fetchone()[0] == 0

    def test_different_mode_is_stale(self, conn):
        ensure_observation_columns(conn)
        _row(conn, 1, "high_contrast", 2.0)
        assert conn.execute(STALE_SQL, ("label_mask", 2.0)).fetchone()[0] == 1

    def test_different_scale_is_stale(self, conn):
        ensure_observation_columns(conn)
        _row(conn, 1, "label_mask", 3.0)
        assert conn.execute(STALE_SQL, ("label_mask", 2.0)).fetchone()[0] == 1

    def test_only_the_newest_row_per_screenshot_counts(self, conn):
        # Raw OCR is append-only: a re-read leaves the old row in place. Judging
        # staleness on the newest row is what stops a re-read looping forever.
        ensure_observation_columns(conn)
        _row(conn, 1, None, None)
        _row(conn, 1, "label_mask", 2.0)
        assert conn.execute(STALE_SQL, ("label_mask", 2.0)).fetchone()[0] == 0

    def test_other_zones_do_not_trigger_a_reread(self, conn):
        ensure_observation_columns(conn)
        _row(conn, 1, "label_mask", 2.0)
        _row(conn, 1, None, None, zone="status_bar")
        assert conn.execute(STALE_SQL, ("label_mask", 2.0)).fetchone()[0] == 0


class TestConfigStamp:
    def test_resolves_declared_scale(self):
        assert config_stamp({"preprocess": "label_mask", "scale": 2.0}) == ("label_mask", 2.0)

    def test_falls_back_to_mode_default(self):
        assert config_stamp({"preprocess": "high_contrast"}) == ("high_contrast", 2.0)

    def test_missing_mode_reads_as_none(self):
        assert config_stamp({}) == ("none", 1.0)

    def test_matches_the_live_zone_config(self):
        from fr24.rlsm_zones import ZONE_OCR_CONFIG
        mode, scale = config_stamp(ZONE_OCR_CONFIG["label_layer"])
        assert mode != "none" and scale >= 1.0
