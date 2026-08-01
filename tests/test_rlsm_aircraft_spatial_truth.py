"""End-to-end invariants for RLSM aircraft spatial truth v0.1."""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

import pytest

from fr24.rlsm_aircraft_markers import (
    DETECTOR_VERSION,
    detect_image,
    estimate_rotation,
)
from fr24.rlsm_aircraft_markers import (
    run as run_marker_detection,
)
from fr24.rlsm_anchors import anchors_for_screenshot
from fr24.rlsm_georeference import (
    GEOREF_VERSION,
    derive_zoom_rungs,
    fit_screenshot,
    load_persisted_affines,
)
from fr24.rlsm_georeference import (
    run as run_georeference,
)
from fr24.rlsm_spatial_schema import AIRCRAFT_SPATIAL_COLUMNS, ensure_spatial_schema

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "data" / "rlsm" / "schema.sql"
NOW = "2026-08-01T00:00:00Z"


def _new_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def _insert_screenshot(
    conn: sqlite3.Connection,
    screenshot_id: int,
    rel_path: str,
    *,
    availability: str = "present",
    near_dup_group_id: int | None = None,
) -> None:
    conn.execute(
        """INSERT INTO screenshots
           (screenshot_id, sha256, filename, rel_path, ext, size_bytes,
            width, height, near_dup_group_id, ingest_status, source_availability,
            ingested_at)
           VALUES (?,?,?,?,'.png',1,200,400,?,'ok',?,?)""",
        (
            screenshot_id,
            f"{screenshot_id:064x}",
            Path(rel_path).name,
            rel_path,
            near_dup_group_id,
            availability,
            NOW,
        ),
    )


def _insert_aircraft(
    conn: sqlite3.Connection,
    screenshot_id: int,
    registration: str,
    *,
    heading: int = 137,
) -> int:
    cursor = conn.execute(
        """INSERT INTO aircraft_observations
           (screenshot_id, registration, heading_deg, identity_status,
            confidence, source_zone, observed_at)
           VALUES (?, ?, ?, 'confirmed', 0.95, 'aircraft_card', ?)""",
        (screenshot_id, registration, heading, NOW),
    )
    return int(cursor.lastrowid)


def _draw_aircraft(path: Path, centers: list[tuple[int, int]]) -> None:
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    image = Image.new("RGB", (200, 400), (28, 32, 40))
    draw = ImageDraw.Draw(image)
    for cx, cy in centers:
        points = [
            (cx, cy - 10),
            (cx + 3, cy - 5),
            (cx + 2, cy - 5),
            (cx + 2, cy + 3),
            (cx + 5, cy + 7),
            (cx + 5, cy + 9),
            (cx + 1, cy + 7),
            (cx - 5, cy + 9),
            (cx - 5, cy + 7),
            (cx - 1, cy + 3),
            (cx - 1, cy - 5),
            (cx - 3, cy - 5),
        ]
        draw.polygon(points, fill=(255, 205, 0))
    image.save(path)


def _draw_round_distractor(path: Path) -> None:
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    image = Image.new("RGB", (200, 400), (28, 32, 40))
    ImageDraw.Draw(image).ellipse((94, 74, 106, 86), fill=(255, 205, 0))
    image.save(path)


def _bind_marker(
    conn: sqlite3.Connection,
    screenshot_id: int,
    aircraft_obs_id: int,
    *,
    pixel_x: float = 100.0,
    pixel_y: float = 120.0,
) -> None:
    frame = conn.execute(
        """INSERT INTO aircraft_marker_frames
           (screenshot_id, detector_version, status, candidate_count,
            selected_candidate_rank, viewport_x, viewport_y, viewport_w,
            viewport_h, reason, observed_at)
           VALUES (?, ?, 'selected', 1, 1, 0, 20, 200, 240,
                   'fixture selected marker', ?)""",
        (screenshot_id, DETECTOR_VERSION, NOW),
    )
    frame_id = int(frame.lastrowid)
    conn.execute(
        """INSERT INTO aircraft_marker_detections
           (marker_frame_id, screenshot_id, aircraft_obs_id, candidate_rank,
            selected, bbox_x, bbox_y, bbox_w, bbox_h, centroid_x, centroid_y,
            rotation_deg, rotation_status, area_px, hue_deg, saturation, value,
            fill_ratio, axis_ratio, direction_asymmetry, silhouette_hash,
            confidence, features_json, observed_at)
           VALUES (?, ?, ?, 1, 1, 95, 111, 10, 18, ?, ?, 42,
                   'resolved', 80, 48, 1, 1, 0.44, 2.1, 0.2,
                   '0123456789abcdef', 0.95, '{}', ?)""",
        (frame_id, screenshot_id, aircraft_obs_id, pixel_x, pixel_y, NOW),
    )
    conn.execute(
        """UPDATE aircraft_observations
           SET pixel_x=?, pixel_y=?, icon_rotation_deg=42,
               marker_confidence=0.95, marker_method=?
           WHERE aircraft_obs_id=?""",
        (pixel_x, pixel_y, DETECTOR_VERSION, aircraft_obs_id),
    )


def test_spatial_schema_is_idempotent_and_constrained(tmp_path: Path) -> None:
    db = tmp_path / "spatial.sqlite"
    conn = _new_db(db)

    ensure_spatial_schema(conn)
    ensure_spatial_schema(conn)

    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(aircraft_observations)")
    }
    assert set(AIRCRAFT_SPATIAL_COLUMNS) <= columns
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "aircraft_marker_frames",
        "aircraft_marker_detections",
        "screenshot_georeferences",
        "zoom_ladder_rungs",
    } <= tables

    _insert_screenshot(conn, 1, "images/one.png")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO aircraft_observations
               (screenshot_id, icon_rotation_deg, observed_at)
               VALUES (1, 360, ?)""",
            (NOW,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO aircraft_observations
               (screenshot_id, pixel_x, observed_at)
               VALUES (1, 10, ?)""",
            (NOW,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO aircraft_observations
               (screenshot_id, pixel_x, pixel_y, marker_confidence,
                marker_method, position_lat, position_lon, position_method,
                position_confidence, position_error_m, position_observed_at,
                observed_at)
               VALUES (1, 10, 20, 0.9, 'fixture', 18.2, -66.5,
                       'multi_anchor_affine', 0.8, 501, ?, ?)""",
            (NOW, NOW),
        )
    conn.close()


def test_spatial_migration_upgrades_a_legacy_observation_table(
    tmp_path: Path,
) -> None:
    db = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE screenshots (screenshot_id INTEGER PRIMARY KEY);
        CREATE TABLE processing_runs (run_id INTEGER PRIMARY KEY);
        CREATE TABLE aircraft_observations (
            aircraft_obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
            screenshot_id INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
            heading_deg INTEGER,
            observed_at TEXT NOT NULL
        );
        INSERT INTO screenshots (screenshot_id) VALUES (1);
        """
    )

    ensure_spatial_schema(conn)

    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(aircraft_observations)")
    }
    assert set(AIRCRAFT_SPATIAL_COLUMNS) <= columns
    conn.execute(
        """INSERT INTO aircraft_observations
           (screenshot_id, heading_deg, observed_at) VALUES (1, 137, ?)""",
        (NOW,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """UPDATE aircraft_observations SET pixel_x=10
               WHERE aircraft_obs_id=1"""
        )
    conn.close()


def test_spatial_exports_are_reproducible_and_include_contract_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fr24 import rlsm_export

    db = tmp_path / "exports.sqlite"
    conn = _new_db(db)
    _insert_screenshot(conn, 1, "images/export.png")
    _insert_aircraft(conn, 1, "N100AA")
    conn.commit()
    conn.close()

    output_dir = tmp_path / "outputs"
    monkeypatch.setattr(rlsm_export, "DB", db)
    monkeypatch.setattr(rlsm_export, "OUTS", output_dir)
    written = rlsm_export.export_all()

    expected = {
        "aircraft_observations.csv",
        "aircraft_marker_frames.csv",
        "aircraft_marker_detections.csv",
        "screenshot_georeferences.csv",
        "zoom_ladder_rungs.csv",
    }
    assert expected <= set(written)
    assert all((output_dir / filename).is_file() for filename in expected)
    aircraft_header = (output_dir / "aircraft_observations.csv").read_text(
        encoding="utf-8"
    ).splitlines()[0]
    assert '"pixel_x"' in aircraft_header
    assert '"icon_rotation_deg"' in aircraft_header
    assert '"position_error_m"' in aircraft_header


def test_pipeline_status_and_report_apply_the_scale_bar_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fr24 import rlsm_pipeline

    db = tmp_path / "status.sqlite"
    conn = _new_db(db)
    for screenshot_id in (1, 2):
        _insert_screenshot(conn, screenshot_id, f"images/{screenshot_id}.png")
        obs_id = _insert_aircraft(conn, screenshot_id, f"N{screenshot_id:03d}AA")
        _bind_marker(conn, screenshot_id, obs_id)

    conn.execute(
        """INSERT INTO screenshot_georeferences
           (screenshot_id, georef_version, status, method, viewport_profile,
            viewport_x, viewport_y, viewport_w, viewport_h, anchor_count,
            lon0, dlon_dx, lat0, dlat_dy, scale_x_m_per_px,
            scale_y_m_per_px, scale_m_per_px, scale_axis_disagreement,
            fit_residual_m, confidence, estimated_error_m, evidence_json,
            observed_at)
           VALUES (1, ?, 'located', 'multi_anchor_affine',
                   '200x400:0,20,200,240', 0, 20, 200, 240, 2,
                   -67, 0.001, 19, -0.001, 105, 111, 108, 0.056,
                   100, 0.82, 100, '{}', ?)""",
        (GEOREF_VERSION, NOW),
    )
    conn.execute(
        """INSERT INTO screenshot_georeferences
           (screenshot_id, georef_version, status, method, viewport_profile,
            viewport_x, viewport_y, viewport_w, viewport_h, anchor_count,
            confidence, evidence_json, observed_at)
           VALUES (2, ?, 'unclassified', 'unclassified',
                   '200x400:0,20,200,240', 0, 20, 200, 240, 1,
                   0.3, '{}', ?)""",
        (GEOREF_VERSION, NOW),
    )
    conn.execute(
        """UPDATE aircraft_observations
           SET position_lat=18.2, position_lon=-66.5,
               position_method='multi_anchor_affine',
               position_confidence=0.82, position_error_m=150,
               position_observed_at=?
           WHERE screenshot_id=1""",
        (NOW,),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(rlsm_pipeline, "REPO", tmp_path)
    monkeypatch.setattr(rlsm_pipeline, "DB", db)
    status = rlsm_pipeline.collect_status()

    assert status["aircraft_marker_accounting_complete"] is True
    assert status["georeference_accounting_complete"] is True
    assert status["aircraft_positions"] == 1
    assert status["scale_bar_recoverable_frames"] == 2
    assert status["scale_bar_unresolved_recoverable_frames"] == 1
    assert status["scale_bar_unresolved_recoverable_rate"] == pytest.approx(0.5)
    assert status["scale_bar_ocr_recommended"] is True
    report = rlsm_pipeline.build_report()
    assert "marker accounting complete | yes" in report
    assert "georeference accounting complete | yes" in report
    assert "dedicated scale-bar OCR recommended" in report


def test_rotation_contract_is_clockwise_and_nullable_for_an_axis() -> None:
    symmetric = [(10, y) for y in range(21)]
    rotation, status, _, _, axis = estimate_rotation(symmetric)
    assert rotation is None
    assert status == "axis_only"
    assert axis == pytest.approx(0.0)

    # A dense tail below a long upper extent resolves toward image-up (0 deg).
    directed = [(10, y) for y in range(21)] + [(x, y) for y in range(13, 21) for x in range(8, 13)]
    rotation, status, _, _, _ = estimate_rotation(directed)
    assert status == "resolved"
    assert rotation is not None
    assert rotation < 15 or rotation > 345
    assert 0 <= rotation < 360


def test_marker_detector_accounts_for_every_frame_and_never_guesses(
    tmp_path: Path,
) -> None:
    db = tmp_path / "markers.sqlite"
    conn = _new_db(db)
    images = tmp_path / "images"
    images.mkdir()

    _draw_aircraft(images / "selected.png", [(100, 80)])
    _draw_aircraft(images / "two-observations.png", [(100, 80)])
    _draw_aircraft(images / "two-candidates.png", [(65, 80), (135, 80)])
    _draw_round_distractor(images / "round-distractor.png")

    for screenshot_id, name in enumerate(
        [
            "selected.png",
            "two-observations.png",
            "missing.png",
            "round-distractor.png",
            "two-candidates.png",
        ],
        start=1,
    ):
        availability = "missing_on_disk" if screenshot_id == 3 else "present"
        _insert_screenshot(
            conn,
            screenshot_id,
            f"images/{name}",
            availability=availability,
        )
    selected_obs = _insert_aircraft(conn, 1, "N100AA")
    _insert_aircraft(conn, 2, "N200AA")
    _insert_aircraft(conn, 2, "N201AA")
    missing_obs = _insert_aircraft(conn, 3, "N300AA")
    distractor_obs = _insert_aircraft(conn, 4, "N400AA")
    ambiguous_obs = _insert_aircraft(conn, 5, "N500AA")
    conn.commit()
    conn.close()

    result = run_marker_detection(db, tmp_path)
    assert result["fully_accounted"] is True
    assert result["processed"] == result["targets"] == 5

    conn = sqlite3.connect(db)
    statuses = dict(
        conn.execute(
            "SELECT screenshot_id, status FROM aircraft_marker_frames ORDER BY screenshot_id"
        )
    )
    assert statuses == {
        1: "selected",
        2: "ambiguous_observation",
        3: "missing_source",
        4: "no_marker",
        5: "ambiguous_candidates",
    }
    assert conn.execute("SELECT COUNT(*) FROM aircraft_marker_frames").fetchone()[0] == 5
    assert conn.execute(
        "SELECT COUNT(*) FROM aircraft_marker_detections WHERE selected=1"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT candidate_count FROM aircraft_marker_frames WHERE screenshot_id=5"
    ).fetchone()[0] == 2

    selected = conn.execute(
        """SELECT pixel_x, pixel_y, icon_rotation_deg, marker_method, heading_deg
           FROM aircraft_observations WHERE aircraft_obs_id=?""",
        (selected_obs,),
    ).fetchone()
    assert selected[0] == pytest.approx(100.0, abs=1.0)
    assert selected[1] == pytest.approx(80.0, abs=2.0)
    assert 0 <= selected[2] < 360
    assert selected[3] == DETECTOR_VERSION
    assert selected[4] == 137

    # These gold distractor/ambiguous cases must never acquire a silent binding.
    for obs_id in (missing_obs, distractor_obs, ambiguous_obs):
        assert conn.execute(
            "SELECT pixel_x FROM aircraft_observations WHERE aircraft_obs_id=?",
            (obs_id,),
        ).fetchone()[0] is None
    assert {row[0] for row in conn.execute("SELECT DISTINCT heading_deg FROM aircraft_observations")} == {137}
    conn.close()

    # Idempotent resume: all five terminal decisions suppress repeat work.
    rerun = run_marker_detection(db, tmp_path)
    assert rerun["targets"] == 0


def test_detector_rejects_round_high_saturation_glyph(tmp_path: Path) -> None:
    path = tmp_path / "round.png"
    _draw_round_distractor(path)
    Image = pytest.importorskip("PIL.Image")
    with Image.open(path) as image:
        _, candidates = detect_image(image)
    assert candidates == []


def test_zoom_ladder_assigns_only_supported_power_of_two_scales() -> None:
    records = []
    for screenshot_id, scale in enumerate([100, 100, 100, 200, 200, 200, 145], start=1):
        records.append(
            {
                "screenshot_id": screenshot_id,
                "scale": scale,
                "dlon_dx": scale / 100_000,
                "dlat_dy": -scale / 111_000,
            }
        )

    rungs, unassigned = derive_zoom_rungs(records)

    assert unassigned == [7]
    assert [row["zoom_rung"] for row in rungs] == [0, 1]
    assert [row["support_count"] for row in rungs] == [3, 3]
    assert all(row["eligible_for_transfer"] for row in rungs)
    assert rungs[1]["scale_m_per_px"] == pytest.approx(
        2 * rungs[0]["scale_m_per_px"]
    )

    evidence_only, unassigned = derive_zoom_rungs(records[:2])
    assert unassigned == []
    assert evidence_only[0]["support_count"] == 2
    assert evidence_only[0]["eligible_for_transfer"] == 0


def test_bad_affine_geometry_is_rejected() -> None:
    # X and Y scales disagree by 2x even though each axis is internally exact.
    anchors = [
        (10.0, 20.0, 18.9, -67.0),
        (110.0, 120.0, 18.9 - 200 / 111_000, -67.0 + 100 / 105_000),
    ]
    result = fit_screenshot(anchors, (0, 20, 200, 240))
    assert result["status"] == "rejected_geometry"


def test_multi_anchor_and_one_anchor_projection_with_bounded_error(
    tmp_path: Path,
) -> None:
    db = tmp_path / "georef.sqlite"
    conn = _new_db(db)
    center_lat = 18.88
    scale_m_per_px = 100.0
    dlon_dx = scale_m_per_px / (111_000 * math.cos(math.radians(center_lat)))
    dlat_dy = -scale_m_per_px / 111_000
    lon0 = -67.2
    lat0 = 19.0

    def geo(px: float, py: float) -> tuple[float, float]:
        return lat0 + dlat_dy * py, lon0 + dlon_dx * px

    observation_ids: dict[int, int] = {}
    groups = {1: 7, 2: 2, 3: 3, 4: 7, 5: 99, 6: 100}
    for screenshot_id in range(1, 7):
        _insert_screenshot(
            conn,
            screenshot_id,
            f"images/georef-{screenshot_id}.png",
            near_dup_group_id=groups[screenshot_id],
        )
        obs_id = _insert_aircraft(conn, screenshot_id, f"N{screenshot_id:03d}AA")
        observation_ids[screenshot_id] = obs_id
        _bind_marker(conn, screenshot_id, obs_id)

    for screenshot_id in (1, 2, 3):
        for px, py in ((20.0, 40.0), (160.0, 220.0)):
            lat, lon = geo(px, py)
            conn.execute(
                """INSERT INTO geo_anchors
                   (screenshot_id, anchor_kind, pixel_x, pixel_y, lat, lon,
                    confidence, source, observed_at)
                   VALUES (?, 'derived', ?, ?, ?, ?, 1, 'fixture', ?)""",
                (screenshot_id, px, py, lat, lon, NOW),
            )

    for screenshot_id in (4, 5):
        px, py = 70.0, 100.0
        lat, lon = geo(px, py)
        conn.execute(
            """INSERT INTO geo_anchors
               (screenshot_id, anchor_kind, pixel_x, pixel_y, lat, lon,
                confidence, source, observed_at)
               VALUES (?, 'derived', ?, ?, ?, ?, 1, 'fixture', ?)""",
            (screenshot_id, px, py, lat, lon, NOW),
        )

    # These circular fixed-bounds assumptions must not train or fit anything.
    for px, py in ((20.0, 40.0), (160.0, 220.0)):
        lat, lon = geo(px, py)
        conn.execute(
            """INSERT INTO geo_anchors
               (screenshot_id, anchor_kind, pixel_x, pixel_y, lat, lon,
                confidence, source, observed_at)
               VALUES (6, 'static', ?, ?, ?, ?, 0.65, 'fixed_pr_bounds', ?)""",
            (px, py, lat, lon, NOW),
        )
    conn.commit()

    assert anchors_for_screenshot(
        conn, 6, {}, include_static_projected=False
    ) == []
    assert len(anchors_for_screenshot(conn, 6, {})) == 2
    conn.close()

    result = run_georeference(db, tmp_path / "missing-places.geojson")
    assert result["targets"] == 6
    assert result["statuses"] == {"located": 4, "unclassified": 2}
    assert result["one_anchor_recovered"] == 1
    assert result["aircraft_positions_projected"] == 4

    conn = sqlite3.connect(db)
    assert conn.execute(
        "SELECT COUNT(*) FROM screenshot_georeferences WHERE georef_version=?",
        (GEOREF_VERSION,),
    ).fetchone()[0] == 6
    rung = conn.execute(
        """SELECT zoom_rung, support_count, eligible_for_transfer
           FROM zoom_ladder_rungs"""
    ).fetchone()
    assert rung == (0, 3, 1)
    assert conn.execute(
        "SELECT method FROM screenshot_georeferences WHERE screenshot_id=4"
    ).fetchone()[0] == "one_anchor_zoom_rung"
    assert conn.execute(
        "SELECT anchor_count FROM screenshot_georeferences WHERE screenshot_id=6"
    ).fetchone()[0] == 0

    expected_lat, expected_lon = geo(100.0, 120.0)
    located = conn.execute(
        """SELECT screenshot_id, position_lat, position_lon, position_method,
                  position_error_m
           FROM aircraft_observations
           WHERE position_lat IS NOT NULL ORDER BY screenshot_id"""
    ).fetchall()
    assert [row[0] for row in located] == [1, 2, 3, 4]
    assert all(row[1] == pytest.approx(expected_lat, abs=1e-8) for row in located)
    assert all(row[2] == pytest.approx(expected_lon, abs=1e-8) for row in located)
    assert all(0 <= row[4] <= 500 for row in located)
    assert conn.execute(
        "SELECT position_lat FROM aircraft_observations WHERE screenshot_id=5"
    ).fetchone()[0] is None
    assert conn.execute(
        "SELECT position_lat FROM aircraft_observations WHERE screenshot_id=6"
    ).fetchone()[0] is None
    assert {row[0] for row in conn.execute("SELECT DISTINCT heading_deg FROM aircraft_observations")} == {137}
    assert set(load_persisted_affines(conn)) == {1, 2, 3, 4}

    evidence = json.loads(
        conn.execute(
            "SELECT evidence_json FROM screenshot_georeferences WHERE screenshot_id=4"
        ).fetchone()[0]
    )
    assert evidence["independent_zoom_evidence"] == "near_dup_group"
    assert evidence["source_screenshot_id"] in {1, 2, 3}
    conn.close()
