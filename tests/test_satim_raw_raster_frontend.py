from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

from fr24.calibration.l5_tile_seam_shadow_calibration import classify_candidate_strict
from fr24.calibration.satim_raw_raster_frontend import extract_raw_raster_candidates


def _write_shadow_fixture(path: Path) -> None:
    """Synthetic cloud-adjacent diffuse dark region; not a certified seam."""
    h, w = 256, 192
    rgb = np.full((h, w, 3), 150, dtype=np.uint8)

    # Terrain-like low-frequency gradient.
    for y in range(h):
        rgb[y, :, :] = np.clip(rgb[y, :, :] - int(25 * y / h), 0, 255)

    # Bright cloud context.
    yy, xx = np.ogrid[:h, :w]
    cloud = ((xx - 96) ** 2) / (42 ** 2) + ((yy - 62) ** 2) / (28 ** 2) <= 1
    rgb[cloud] = 235

    # Broad diffuse shadow below cloud.
    shadow = ((xx - 103) ** 2) / (38 ** 2) + ((yy - 145) ** 2) / (78 ** 2) <= 1
    rgb[shadow] = (rgb[shadow].astype(np.float32) * 0.52).astype(np.uint8)

    Image.fromarray(rgb, mode="RGB").save(path)


def test_raw_frontend_detects_visual_candidate_without_origin_promotion(tmp_path: Path) -> None:
    image_path = tmp_path / "shadow.png"
    _write_shadow_fixture(image_path)

    rows = extract_raw_raster_candidates(
        image_path,
        source_image_id="fixture-shadow-001",
        source_uri=str(image_path),
        capture_datetime_utc="2026-09-17T15:58:11Z",
        aoi_id="fixture",
    )

    assert rows
    assert all(row["review_state"] == "manual_review_required" for row in rows)
    assert all("SINGLE_FRAME_ORIGIN_UNRESOLVED" in row["contradiction_flags"] for row in rows)
    assert all(float(row.get("screen_locked_score", 0)) == 0 for row in rows)
    assert all(float(row.get("ground_fixed_score", 0)) == 0 for row in rows)
    assert all(float(row.get("provider_tile_grid_binding_score", 0)) == 0 for row in rows)
    assert all(float(row.get("independent_ground_feature_binding_score", 0)) == 0 for row in rows)


def test_single_frame_candidate_cannot_pass_strict_origin_gate(tmp_path: Path) -> None:
    image_path = tmp_path / "shadow.png"
    _write_shadow_fixture(image_path)

    rows = extract_raw_raster_candidates(
        image_path,
        source_image_id="fixture-shadow-001",
        source_uri=str(image_path),
        capture_datetime_utc="2026-09-17T15:58:11Z",
        aoi_id="fixture",
    )

    strict = [classify_candidate_strict(row) for row in rows]
    assert strict
    assert all(result["origin_state"] != "PASS" for result in strict)
    assert all(result["resolved_origin"] == "UNRESOLVED" for result in strict)
    assert not any(result["decision"] == "probable_display_tile_edge" for result in strict)
    assert not any(result["decision"] == "probable_source_mosaic_cutline" for result in strict)
    assert not any(
        result["leading_origin_candidate"] == "PHYSICAL_GROUND_FEATURE" and result["origin_state"] == "PASS"
        for result in strict
    )
