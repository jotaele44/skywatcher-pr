"""Repo-native raw-raster frontend for SATIM L5 visual candidate generation.

This module closes the missing screenshot -> image metrics boundary without
promoting visual measurements into causal identity. It produces conservative
candidate rows for the existing ``satim_raster_candidate_extraction`` and L5
classifiers.

The frontend intentionally uses only Pillow + NumPy when available through the
existing runtime. No geographic identity, imagery epoch, seam origin, or
physical-ground identity is inferred from a single raster.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .satim_raster_candidate_extraction import candidate_from_detection


@dataclass(frozen=True)
class RawRasterConfig:
    """Conservative single-frame extraction controls."""

    analysis_grid: int = 32
    dark_percentile: float = 20.0
    bright_percentile: float = 85.0
    min_component_cells: int = 3
    min_contrast: float = 0.08
    max_single_frame_origin_confidence: float = 0.49


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _luminance(rgb: np.ndarray) -> np.ndarray:
    arr = rgb.astype(np.float32) / 255.0
    return 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]


def _grid_reduce(values: np.ndarray, grid: int) -> np.ndarray:
    """Mean-pool an image into a coarse deterministic grid."""
    h, w = values.shape
    gh = max(1, min(grid, h))
    gw = max(1, min(grid, w))
    ys = np.linspace(0, h, gh + 1, dtype=int)
    xs = np.linspace(0, w, gw + 1, dtype=int)
    pooled = np.zeros((gh, gw), dtype=np.float32)
    for iy in range(gh):
        for ix in range(gw):
            cell = values[ys[iy]:ys[iy + 1], xs[ix]:xs[ix + 1]]
            pooled[iy, ix] = float(cell.mean()) if cell.size else 0.0
    return pooled


def _neighbors(y: int, x: int, h: int, w: int):
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        ny, nx = y + dy, x + dx
        if 0 <= ny < h and 0 <= nx < w:
            yield ny, nx


def _components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    seen: set[tuple[int, int]] = set()
    out: list[list[tuple[int, int]]] = []
    h, w = mask.shape
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or (y, x) in seen:
                continue
            stack = [(y, x)]
            seen.add((y, x))
            comp: list[tuple[int, int]] = []
            while stack:
                cy, cx = stack.pop()
                comp.append((cy, cx))
                for nxt in _neighbors(cy, cx, h, w):
                    if mask[nxt] and nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            out.append(comp)
    return out


def _bbox_from_cells(cells: list[tuple[int, int]], image_shape: tuple[int, int], grid_shape: tuple[int, int]) -> tuple[int, int, int, int]:
    h, w = image_shape
    gh, gw = grid_shape
    ys = [c[0] for c in cells]
    xs = [c[1] for c in cells]
    y1 = int(min(ys) * h / gh)
    y2 = int((max(ys) + 1) * h / gh)
    x1 = int(min(xs) * w / gw)
    x2 = int((max(xs) + 1) * w / gw)
    return x1, y1, x2, y2


def _component_scores(
    lum: np.ndarray,
    bbox: tuple[int, int, int, int],
    bright_mask: np.ndarray,
) -> dict[str, float]:
    x1, y1, x2, y2 = bbox
    region = lum[y1:y2, x1:x2]
    if region.size == 0:
        return {}
    pad = max(4, int(max(x2 - x1, y2 - y1) * 0.15))
    ax1, ay1 = max(0, x1 - pad), max(0, y1 - pad)
    ax2, ay2 = min(lum.shape[1], x2 + pad), min(lum.shape[0], y2 + pad)
    context = lum[ay1:ay2, ax1:ax2]
    mean_region = float(region.mean())
    mean_context = float(context.mean()) if context.size else mean_region
    contrast = _clamp01(max(0.0, mean_context - mean_region) / max(mean_context, 1e-6))

    height = max(1, y2 - y1)
    width = max(1, x2 - x1)
    elongation = max(height, width) / max(1.0, min(height, width))
    rectangular = _clamp01(1.0 / max(1.0, elongation))

    # Straightness is deliberately conservative: bounding-box geometry is not
    # equivalent to a measured linear seam.
    straightness = _clamp01(0.35 * rectangular + 0.15)

    # Bright/cloud adjacency proxy: presence of very bright pixels in a padded
    # neighborhood surrounding the dark candidate. This is only context.
    bright_neighborhood = bright_mask[ay1:ay2, ax1:ax2]
    bright_adj = _clamp01(float(bright_neighborhood.mean()) * 8.0) if bright_neighborhood.size else 0.0

    return {
        "radiometric_discontinuity_score": contrast,
        "color_discontinuity_score": contrast,
        "straight_boundary_score": straightness,
        "rectangular_patch_score": rectangular,
        "cloud_mask_intersection": bright_adj,
        "shadow_mask_intersection": max(contrast, 0.1 if bright_adj > 0 else 0.0),
        "texture_discontinuity_score": _clamp01(float(region.std()) / 0.25),
        # Single-frame frontend cannot establish these origin variables.
        "multi_date_persistence": 0.0,
        "dem_hillshade_alignment": 0.0,
        "screen_locked_score": 0.0,
        "ground_fixed_score": 0.0,
        "provider_tile_grid_binding_score": 0.0,
        "adjacent_zoom_ground_persistence_score": 0.0,
        "source_mosaic_metadata_binding_score": 0.0,
        "independent_ground_feature_binding_score": 0.0,
    }


def extract_raw_raster_candidates(
    image_path: str | Path,
    *,
    source_image_id: str,
    source_uri: str,
    capture_datetime_utc: str,
    aoi_id: str,
    config: RawRasterConfig | None = None,
) -> list[dict[str, Any]]:
    """Extract conservative dark/radiometric candidates directly from pixels.

    Output is suitable for the existing SATIM visual-ledger contract. A single
    image can create visual candidates but cannot certify seam origin, persistence,
    screen-lock, ground fixation, provider-grid binding, or a physical feature.
    """
    cfg = config or RawRasterConfig()
    rgb = np.asarray(Image.open(image_path).convert("RGB"))
    lum = _luminance(rgb)
    pooled = _grid_reduce(lum, cfg.analysis_grid)

    dark_threshold = float(np.percentile(pooled, cfg.dark_percentile))
    bright_threshold = float(np.percentile(lum, cfg.bright_percentile))
    dark_cells = pooled <= dark_threshold
    bright_mask = lum >= bright_threshold

    components = [c for c in _components(dark_cells) if len(c) >= cfg.min_component_cells]
    rows: list[dict[str, Any]] = []
    for index, cells in enumerate(components, start=1):
        bbox = _bbox_from_cells(cells, lum.shape, pooled.shape)
        scores = _component_scores(lum, bbox, bright_mask)
        if scores.get("radiometric_discontinuity_score", 0.0) < cfg.min_contrast:
            continue
        x1, y1, x2, y2 = bbox
        detection = {
            "candidate_kind": "dark_radiometric_region",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [x1, y1], [x2, y1], [x2, y2], [x1, y2], [x1, y1]
                ]],
            },
            "classification": "indeterminate",
            "confidence": min(
                cfg.max_single_frame_origin_confidence,
                max(scores["radiometric_discontinuity_score"], scores["cloud_mask_intersection"]),
            ),
            "review_state": "manual_review_required",
            "contradiction_flags": ["SINGLE_FRAME_ORIGIN_UNRESOLVED"],
            **scores,
        }
        row = candidate_from_detection(
            detection,
            source_image_id=source_image_id,
            source_uri=source_uri,
            capture_datetime_utc=capture_datetime_utc,
            aoi_id=aoi_id,
            visual_id_prefix="SATIM-RAW",
            sequence=index,
        )
        # Preserve raw L5 aliases required by downstream legacy/strict classifiers.
        row.update(scores)
        rows.append(row)
    return rows
