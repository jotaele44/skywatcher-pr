"""Fail-closed aircraft-marker localization for RLSM screenshots.

The existing icon channel searches only beside OCR-located place labels.  This
module reuses its color/component primitives but searches the bounded FR24 map
viewport for the selected aircraft glyph.  It records every plausible
candidate and exactly one terminal frame decision.  Pixel coordinates are
copied onto ``aircraft_observations`` only when one observation and one
well-separated candidate can be bound without guessing.

Coordinate contract
-------------------
* source image is EXIF-transposed before measurement;
* origin is the source image's upper-left pixel;
* x increases right and y increases down;
* rotation is 0 degrees at image-up and increases clockwise;
* a symmetric silhouette retains an axis in ``features_json`` but its
  direction-bearing ``rotation_deg`` remains NULL.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from fr24.rlsm_icons import average_hash, circular_mean_hue, connected_components
from fr24.rlsm_spatial_schema import ensure_spatial_schema
from fr24.rlsm_zones import zones_for

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - preflight reports the missing dependency
    Image = None  # type: ignore
    ImageOps = None  # type: ignore

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover - optional HEIC support
    pass


REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
DETECTOR_VERSION = "rlsm-aircraft-marker-v1"

# Known high-saturation FR24 marker families.  The broad cyan range is retained
# for UI-version variation, but receives a weaker score than yellow/red.  A
# pixel outside these ranges is never enough by itself to become a marker.
HUE_RANGES = (
    (0.0, 24.0),
    (34.0, 78.0),
    (175.0, 225.0),
    (300.0, 360.0),
)
MIN_SATURATION = 0.55
MIN_VALUE = 0.32
SELECTION_THRESHOLD = 0.78
SELECTION_MARGIN = 0.10
MIN_AXIS_RATIO = 1.18


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass(frozen=True)
class MarkerCandidate:
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    centroid_x: float
    centroid_y: float
    rotation_deg: float | None
    rotation_status: str
    area_px: int
    hue_deg: float
    saturation: float
    value: float
    fill_ratio: float
    axis_ratio: float
    direction_asymmetry: float
    silhouette_hash: str
    confidence: float
    features_json: str


def map_viewport(width: int, height: int) -> tuple[int, int, int, int]:
    """Return the canonical label/map viewport in source-image coordinates."""
    for zone in zones_for(width, height):
        if zone.name == "label_layer":
            return zone.x, zone.y, zone.w, zone.h
    raise ValueError("label_layer viewport is not configured")


def _hue_prior(hue: float) -> float:
    hue %= 360.0
    if 34.0 <= hue <= 78.0:
        return 1.0
    if hue <= 24.0 or hue >= 300.0:
        return 0.95
    if 175.0 <= hue <= 225.0:
        return 0.72
    return 0.0


def _is_marker_color(h: int, s: int, v: int) -> bool:
    hue = h * 360.0 / 255.0
    saturation = s / 255.0
    value = v / 255.0
    return (
        saturation >= MIN_SATURATION
        and value >= MIN_VALUE
        and any(lo <= hue <= hi for lo, hi in HUE_RANGES)
    )


def estimate_rotation(
    pixels: list[tuple[int, int]],
) -> tuple[float | None, str, float, float, float | None]:
    """Estimate a directed principal axis without a CV dependency.

    Returns ``(rotation, status, axis_ratio, asymmetry, axis_rotation)``.
    ``axis_rotation`` is always modulo 180 when an axis exists; ``rotation`` is
    emitted only when the two ends have enough extent asymmetry to resolve the
    180-degree ambiguity.
    """
    if len(pixels) < 5:
        return None, "isotropic", 1.0, 0.0, None
    mx = sum(p[0] for p in pixels) / len(pixels)
    my = sum(p[1] for p in pixels) / len(pixels)
    xx = sum((x - mx) ** 2 for x, _ in pixels) / len(pixels)
    yy = sum((y - my) ** 2 for _, y in pixels) / len(pixels)
    xy = sum((x - mx) * (y - my) for x, y in pixels) / len(pixels)
    trace = xx + yy
    disc = math.sqrt(max(0.0, (xx - yy) ** 2 + 4.0 * xy * xy))
    major = (trace + disc) / 2.0
    minor = max((trace - disc) / 2.0, 1e-9)
    axis_ratio = math.sqrt(max(major, 1e-9) / minor)
    if axis_ratio < 1.12:
        return None, "isotropic", round(axis_ratio, 4), 0.0, None

    theta = 0.5 * math.atan2(2.0 * xy, xx - yy)
    vx, vy = math.cos(theta), math.sin(theta)
    projections = [(x - mx) * vx + (y - my) * vy for x, y in pixels]
    pos_extent = max(projections)
    neg_extent = -min(projections)
    extent = max(pos_extent, neg_extent, 1e-9)
    asymmetry = abs(pos_extent - neg_extent) / extent
    if pos_extent < neg_extent:
        vx, vy = -vx, -vy

    directed = math.degrees(math.atan2(vx, -vy)) % 360.0
    # Normalize again after rounding so values near north cannot become 360.0
    # (which is equivalent geometrically but violates the persisted [0, 360)
    # contract).
    axis_rotation = round(directed % 180.0, 3) % 180.0
    if asymmetry < 0.12:
        return (
            None,
            "axis_only",
            round(axis_ratio, 4),
            round(asymmetry, 4),
            axis_rotation,
        )
    return (
        round(directed, 3) % 360.0,
        "resolved",
        round(axis_ratio, 4),
        round(asymmetry, 4),
        axis_rotation,
    )


def detect_candidates_from_grids(
    rgb: list[list[tuple[int, int, int]]],
    hsv: list[list[tuple[int, int, int]]],
    offset_x: int = 0,
    offset_y: int = 0,
) -> list[MarkerCandidate]:
    """Detect marker candidates from aligned RGB/HSV viewport grids."""
    if not rgb or not rgb[0] or len(rgb) != len(hsv) or len(rgb[0]) != len(hsv[0]):
        return []
    height, width = len(rgb), len(rgb[0])
    viewport_area = width * height
    mask = [
        [_is_marker_color(*hsv[y][x]) for x in range(width)]
        for y in range(height)
    ]
    min_area = max(18, round(viewport_area * 0.000012))
    max_area = max(120, round(viewport_area * 0.0020))
    expected_area = max(24.0, viewport_area * 0.00011)
    scale = math.sqrt(viewport_area / float(1170 * 1519))
    min_extent = max(3, round(5 * scale))
    max_extent = max(24, round(72 * scale))

    candidates: list[MarkerCandidate] = []
    for comp in connected_components(mask, min_area=min_area):
        if comp["area"] > max_area:
            continue
        if min(comp["w"], comp["h"]) < min_extent:
            continue
        if max(comp["w"], comp["h"]) > max_extent:
            continue
        if comp["aspect"] > 4.0 or not (0.12 <= comp["fill_ratio"] <= 0.92):
            continue

        hues: list[float] = []
        sats: list[float] = []
        vals: list[float] = []
        for x, y in comp["pixels"]:
            hh, ss, vv = hsv[y][x]
            hues.append(hh * 360.0 / 255.0)
            sats.append(ss / 255.0)
            vals.append(vv / 255.0)
        hue = circular_mean_hue(hues, sats)
        saturation = sum(sats) / len(sats)
        value = sum(vals) / len(vals)
        rotation, rotation_status, axis_ratio, asymmetry, axis_rotation = (
            estimate_rotation(comp["pixels"])
        )
        if axis_ratio < MIN_AXIS_RATIO:
            continue

        size_score = math.exp(-abs(math.log(max(comp["area"], 1) / expected_area)))
        compact_score = min(1.0, comp["fill_ratio"] / 0.50)
        axis_score = min(1.0, max(0.0, axis_ratio - 1.0) / 0.8)
        confidence = (
            0.34 * min(1.0, saturation)
            + 0.20 * compact_score
            + 0.20 * size_score
            + 0.16 * _hue_prior(hue)
            + 0.10 * axis_score
        )

        member = set(comp["pixels"])
        binary = [
            [
                255 if (x, y) in member else 0
                for x in range(comp["x"], comp["x"] + comp["w"])
            ]
            for y in range(comp["y"], comp["y"] + comp["h"])
        ]
        features = {
            "axis_rotation_deg": axis_rotation,
            "coordinate_convention": "exif_transposed_origin_upper_left_rotation_clockwise",
            "detector_version": DETECTOR_VERSION,
            "score_terms": {
                "axis": round(axis_score, 4),
                "compact": round(compact_score, 4),
                "hue": round(_hue_prior(hue), 4),
                "saturation": round(saturation, 4),
                "size": round(size_score, 4),
            },
        }
        candidates.append(
            MarkerCandidate(
                bbox_x=offset_x + comp["x"],
                bbox_y=offset_y + comp["y"],
                bbox_w=comp["w"],
                bbox_h=comp["h"],
                centroid_x=round(
                    offset_x + sum(x for x, _ in comp["pixels"]) / comp["area"], 3
                ),
                centroid_y=round(
                    offset_y + sum(y for _, y in comp["pixels"]) / comp["area"], 3
                ),
                rotation_deg=rotation,
                rotation_status=rotation_status,
                area_px=comp["area"],
                hue_deg=round(hue, 3),
                saturation=round(saturation, 4),
                value=round(value, 4),
                fill_ratio=round(comp["fill_ratio"], 4),
                axis_ratio=axis_ratio,
                direction_asymmetry=asymmetry,
                silhouette_hash=average_hash(binary),
                confidence=round(min(0.99, confidence), 4),
                features_json=json.dumps(features, sort_keys=True, separators=(",", ":")),
            )
        )
    return sorted(candidates, key=lambda candidate: (-candidate.confidence, candidate.bbox_y,
                                                     candidate.bbox_x))


def choose_candidate(candidates: list[MarkerCandidate]) -> tuple[int | None, str]:
    """Return a 1-based winning rank, or a fail-closed reason."""
    if not candidates:
        return None, "no candidate passed the color and geometry gates"
    best = candidates[0]
    if best.confidence < SELECTION_THRESHOLD:
        return None, f"top candidate confidence {best.confidence:.3f} below threshold"
    if len(candidates) > 1:
        margin = best.confidence - candidates[1].confidence
        if margin < SELECTION_MARGIN:
            return None, f"top-two candidate margin {margin:.3f} below threshold"
    return 1, "one high-confidence, well-separated candidate"


def detect_image(image) -> tuple[tuple[int, int, int, int], list[MarkerCandidate]]:
    """Decode the map viewport from a Pillow image and run the pure detector."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    width, height = image.size
    viewport = map_viewport(width, height)
    x, y, w, h = viewport
    rgb_crop = image.crop((x, y, x + w, y + h))
    hsv_crop = rgb_crop.convert("HSV")
    # Pillow 12 renamed this iterator ahead of removing ``getdata`` in 14.
    # Do not pass ``image.getdata`` as getattr's default: Python evaluates that
    # default eagerly, which would still fail after the old attribute is removed.
    rgb_flatten = getattr(rgb_crop, "get_flattened_data", None)
    hsv_flatten = getattr(hsv_crop, "get_flattened_data", None)
    if rgb_flatten is None:  # Pillow 10/11 compatibility
        rgb_flatten = rgb_crop.getdata
    if hsv_flatten is None:  # Pillow 10/11 compatibility
        hsv_flatten = hsv_crop.getdata
    rgb_values = list(rgb_flatten())
    hsv_values = list(hsv_flatten())
    rgb = [rgb_values[row * w:(row + 1) * w] for row in range(h)]
    hsv = [hsv_values[row * w:(row + 1) * w] for row in range(h)]
    return viewport, detect_candidates_from_grids(rgb, hsv, x, y)


def _record_frame(
    conn: sqlite3.Connection,
    *,
    screenshot_id: int,
    run_id: int,
    status: str,
    viewport: tuple[int, int, int, int] | None,
    candidates: list[MarkerCandidate],
    selected_rank: int | None,
    aircraft_obs_id: int | None,
    reason: str,
) -> int:
    vx, vy, vw, vh = viewport or (None, None, None, None)
    now = _iso_now()
    cursor = conn.execute(
        """INSERT INTO aircraft_marker_frames
           (screenshot_id, run_id, detector_version, status, candidate_count,
            selected_candidate_rank, viewport_x, viewport_y, viewport_w, viewport_h,
            reason, observed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            screenshot_id,
            run_id,
            DETECTOR_VERSION,
            status,
            len(candidates),
            selected_rank,
            vx,
            vy,
            vw,
            vh,
            reason[:500],
            now,
        ),
    )
    frame_id = int(cursor.lastrowid)
    for rank, candidate in enumerate(candidates, start=1):
        selected = int(rank == selected_rank)
        values = asdict(candidate)
        conn.execute(
            """INSERT INTO aircraft_marker_detections
               (marker_frame_id, screenshot_id, aircraft_obs_id, candidate_rank,
                selected, bbox_x, bbox_y, bbox_w, bbox_h, centroid_x, centroid_y,
                rotation_deg, rotation_status, area_px, hue_deg, saturation, value,
                fill_ratio, axis_ratio, direction_asymmetry, silhouette_hash,
                confidence, features_json, observed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                frame_id,
                screenshot_id,
                aircraft_obs_id if selected else None,
                rank,
                selected,
                values["bbox_x"],
                values["bbox_y"],
                values["bbox_w"],
                values["bbox_h"],
                values["centroid_x"],
                values["centroid_y"],
                values["rotation_deg"],
                values["rotation_status"],
                values["area_px"],
                values["hue_deg"],
                values["saturation"],
                values["value"],
                values["fill_ratio"],
                values["axis_ratio"],
                values["direction_asymmetry"],
                values["silhouette_hash"],
                values["confidence"],
                values["features_json"],
                now,
            ),
        )
    return frame_id


def run(
    db_path: Path = DB,
    repo_root: Path = REPO,
    *,
    budget_sec: float = 86400.0,
    limit: int = 0,
) -> dict:
    """Process every unaccounted screenshot carrying an aircraft observation."""
    if Image is None:
        raise RuntimeError("Pillow is required for aircraft-marker detection")
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    ensure_spatial_schema(conn)
    sql = """SELECT s.screenshot_id, s.rel_path, s.source_availability
             FROM screenshots s
             WHERE EXISTS (
                 SELECT 1 FROM aircraft_observations a
                 WHERE a.screenshot_id = s.screenshot_id
             )
               AND NOT EXISTS (
                 SELECT 1 FROM aircraft_marker_frames f
                 WHERE f.screenshot_id = s.screenshot_id
                   AND f.detector_version = ?
             )
             ORDER BY s.screenshot_id"""
    params: list[object] = [DETECTOR_VERSION]
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    targets = conn.execute(sql, params).fetchall()
    started = _iso_now()
    cursor = conn.execute(
        """INSERT INTO processing_runs
           (run_kind, started_at, status, n_inputs, n_processed, n_failed, notes)
           VALUES ('aircraft_marker', ?, 'in_progress', ?, 0, 0, ?)""",
        (started, len(targets), json.dumps({"detector_version": DETECTOR_VERSION})),
    )
    run_id = int(cursor.lastrowid)
    conn.commit()

    t0 = time.time()
    counts: dict[str, int] = {}
    processed = failed = 0
    for screenshot_id, rel_path, availability in targets:
        if time.time() - t0 > budget_sec:
            break
        # A forced retry of this detector version must not leave its earlier
        # observation-level binding behind when the new decision fails closed.
        conn.execute(
            """UPDATE aircraft_observations
               SET pixel_x=NULL, pixel_y=NULL, icon_rotation_deg=NULL,
                   marker_confidence=NULL, marker_method=NULL,
                   position_lat=NULL, position_lon=NULL, position_method=NULL,
                   position_confidence=NULL, position_error_m=NULL,
                   position_observed_at=NULL
               WHERE screenshot_id=? AND marker_method=?""",
            (screenshot_id, DETECTOR_VERSION),
        )
        obs_ids = [
            int(row[0])
            for row in conn.execute(
                "SELECT aircraft_obs_id FROM aircraft_observations "
                "WHERE screenshot_id=? ORDER BY aircraft_obs_id",
                (screenshot_id,),
            )
        ]
        viewport = None
        candidates: list[MarkerCandidate] = []
        selected_rank = None
        reason = ""

        relative = Path(str(rel_path))
        unsafe_path = relative.is_absolute() or ".." in relative.parts
        full_path = repo_root / relative
        if availability not in ("present", "restored"):
            status, reason = "missing_source", f"source_availability={availability}"
        elif unsafe_path:
            status, reason = "unreadable", "unsafe rel_path"
        elif not full_path.exists():
            status, reason = "missing_source", "source path does not exist"
        else:
            try:
                with Image.open(full_path) as image:
                    image.load()
                    viewport, candidates = detect_image(image)
                candidate_rank, decision_reason = choose_candidate(candidates)
                if len(obs_ids) != 1:
                    status = "ambiguous_observation"
                    reason = f"{len(obs_ids)} aircraft observations; marker not bound"
                elif candidate_rank is None:
                    status = "no_marker" if not candidates else "ambiguous_candidates"
                    reason = decision_reason
                else:
                    status = "selected"
                    selected_rank = candidate_rank
                    reason = decision_reason
            except Exception as exc:  # one corrupt frame must not abort the corpus
                status = "unreadable"
                reason = f"{type(exc).__name__}: {exc}"

        selected_obs = obs_ids[0] if status == "selected" else None
        _record_frame(
            conn,
            screenshot_id=screenshot_id,
            run_id=run_id,
            status=status,
            viewport=viewport,
            candidates=candidates,
            selected_rank=selected_rank,
            aircraft_obs_id=selected_obs,
            reason=reason,
        )
        if selected_obs is not None and selected_rank is not None:
            chosen = candidates[selected_rank - 1]
            conn.execute(
                """UPDATE aircraft_observations
                   SET pixel_x=?, pixel_y=?, icon_rotation_deg=?, marker_confidence=?,
                       marker_method=?
                   WHERE aircraft_obs_id=?""",
                (
                    chosen.centroid_x,
                    chosen.centroid_y,
                    chosen.rotation_deg,
                    chosen.confidence,
                    DETECTOR_VERSION,
                    selected_obs,
                ),
            )
        conn.commit()
        processed += 1
        counts[status] = counts.get(status, 0) + 1
        if status in ("missing_source", "unreadable"):
            failed += 1

    fully_accounted = processed == len(targets)
    conn.execute(
        """UPDATE processing_runs
           SET ended_at=?, status=?, n_processed=?, n_failed=?, notes=?
           WHERE run_id=?""",
        (
            _iso_now(),
            "completed" if fully_accounted else "failed",
            processed,
            failed + len(targets) - processed,
            json.dumps(
                {
                    "detector_version": DETECTOR_VERSION,
                    "statuses": counts,
                    "unprocessed": len(targets) - processed,
                },
                sort_keys=True,
            ),
            run_id,
        ),
    )
    conn.commit()
    conn.close()
    result = {
        "run_id": run_id,
        "targets": len(targets),
        "processed": processed,
        "failed": failed,
        "fully_accounted": fully_accounted,
        "statuses": counts,
        "detector_version": DETECTOR_VERSION,
        "elapsed_sec": round(time.time() - t0, 3),
    }
    if not fully_accounted:
        raise RuntimeError(
            f"aircraft-marker budget expired with {len(targets) - processed} "
            "target frame(s) unaccounted; rerun to resume"
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect selected FR24 aircraft markers.")
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--budget-sec", type=float, default=86400.0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.db, args.repo_root, budget_sec=args.budget_sec, limit=args.limit),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
