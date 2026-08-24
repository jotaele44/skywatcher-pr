"""Deterministic discovery-only image feature extractor for landscape morphology."""
from __future__ import annotations

import math
from pathlib import Path
from PIL import Image
from .models import LandscapeMetrics

METHOD_VERSION = "satim.landscape.extractor.v0.1.0"
METHOD_CONSTANTS = {
    "analysis_max_dimension_px": 192,
    "block_size_px": 12,
    "vegetation_hue_min": 0.25,
    "vegetation_hue_max": 0.72,
    "vegetation_saturation_min": 0.06,
    "forest_value_max": 0.34,
    "soil_hue_max": 0.24,
    "soil_saturation_min": 0.06,
    "soil_value_min": 0.26,
    "bright_cover_saturation_max": 0.13,
    "bright_cover_value_min": 0.43,
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _analysis_size(width: int, height: int, max_dim: int) -> tuple[int, int]:
    if width <= max_dim and height <= max_dim:
        return width, height
    scale = max_dim / max(width, height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _pixels(image: Image.Image):
    flattened = getattr(image, "get_flattened_data", None)
    return flattened() if flattened is not None else image.getdata()


def _classify_pixel(h: int, s: int, v: int) -> tuple[bool, bool, bool, bool, bool]:
    hn, sn, vn = h / 255.0, s / 255.0, v / 255.0
    vegetation = (
        METHOD_CONSTANTS["vegetation_hue_min"] <= hn <= METHOD_CONSTANTS["vegetation_hue_max"]
        and sn >= METHOD_CONSTANTS["vegetation_saturation_min"]
    )
    forest = vegetation and vn <= METHOD_CONSTANTS["forest_value_max"]
    light_green = vegetation and not forest
    soil = (
        hn <= METHOD_CONSTANTS["soil_hue_max"]
        and sn >= METHOD_CONSTANTS["soil_saturation_min"]
        and vn >= METHOD_CONSTANTS["soil_value_min"]
    )
    bright = (
        sn <= METHOD_CONSTANTS["bright_cover_saturation_max"]
        and vn >= METHOD_CONSTANTS["bright_cover_value_min"]
    )
    return vegetation, forest, light_green, soil, bright


def _block_structure_tensor(gray, open_mask, x0, y0, x1, y1):
    open_count = sum(int(open_mask[y][x]) for y in range(y0, y1) for x in range(x0, x1))
    pixel_count = max(1, (x1 - x0) * (y1 - y0))
    jxx = jyy = jxy = 0.0
    gradient_count = 0
    for y in range(max(1, y0), min(len(gray) - 1, y1)):
        row = gray[y]
        for x in range(max(1, x0), min(len(row) - 1, x1)):
            gx = (row[x + 1] - row[x - 1]) / 2.0
            gy = (gray[y + 1][x] - gray[y - 1][x]) / 2.0
            jxx += gx * gx
            jyy += gy * gy
            jxy += gx * gy
            gradient_count += 1
    if gradient_count:
        jxx /= gradient_count
        jyy /= gradient_count
        jxy /= gradient_count
    trace = jxx + jyy
    discriminant = math.sqrt(max(0.0, (jxx - jyy) ** 2 + 4.0 * jxy * jxy))
    anisotropy = discriminant / (trace + 1e-12)
    return _clamp01(anisotropy), max(0.0, math.sqrt(trace)), open_count / pixel_count


def extract_landscape_metrics(path: str | Path) -> LandscapeMetrics:
    image_path = Path(path)
    with Image.open(image_path) as opened:
        rgb = opened.convert("RGB")
        width, height = rgb.size
        size = _analysis_size(width, height, int(METHOD_CONSTANTS["analysis_max_dimension_px"]))
        if size != rgb.size:
            rgb = rgb.resize(size, Image.Resampling.BILINEAR)
        hsv = rgb.convert("HSV")
        aw, ah = rgb.size
        hsv_pixels = list(_pixels(hsv))
        rgb_pixels = list(_pixels(rgb))
    vegetation_count = forest_count = soil_count = bright_count = open_count = 0
    open_mask = [[False] * aw for _ in range(ah)]
    gray = [[0.0] * aw for _ in range(ah)]
    for idx, ((h, s, v), (r, g, b)) in enumerate(zip(hsv_pixels, rgb_pixels, strict=True)):
        y, x = divmod(idx, aw)
        vegetation, forest, light_green, soil, bright = _classify_pixel(h, s, v)
        open_surface = light_green or soil or bright
        vegetation_count += int(vegetation)
        forest_count += int(forest)
        soil_count += int(soil)
        bright_count += int(bright)
        open_count += int(open_surface)
        open_mask[y][x] = open_surface
        gray[y][x] = (float(r) + float(g) + float(b)) / (3.0 * 255.0)
    total = max(1, aw * ah)
    block_size = int(METHOD_CONSTANTS["block_size_px"])
    weighted_anisotropy = weight_total = 0.0
    block_open_fractions = []
    for y0 in range(0, ah, block_size):
        y1 = min(ah, y0 + block_size)
        for x0 in range(0, aw, block_size):
            x1 = min(aw, x0 + block_size)
            anisotropy, edge_energy, open_fraction = _block_structure_tensor(gray, open_mask, x0, y0, x1, y1)
            weight = open_fraction * edge_energy
            weighted_anisotropy += anisotropy * weight
            weight_total += weight
            block_open_fractions.append(open_fraction)
    directional_texture = weighted_anisotropy / weight_total if weight_total else 0.0
    if block_open_fractions:
        mean_open = sum(block_open_fractions) / len(block_open_fractions)
        variance = sum((value - mean_open) ** 2 for value in block_open_fractions) / len(block_open_fractions)
        patch_mosaic = min(1.0, variance / 0.25)
    else:
        patch_mosaic = 0.0
    return LandscapeMetrics(
        width_px=width, height_px=height, analysis_width_px=aw, analysis_height_px=ah,
        vegetation_fraction=_clamp01(vegetation_count / total),
        forest_matrix_fraction=_clamp01(forest_count / total),
        open_surface_fraction=_clamp01(open_count / total),
        exposed_soil_fraction=_clamp01(soil_count / total),
        bright_cover_fraction=_clamp01(bright_count / total),
        directional_texture_score=_clamp01(directional_texture),
        patch_mosaic_score=_clamp01(patch_mosaic),
        extraction_method=METHOD_VERSION, extraction_constants=dict(METHOD_CONSTANTS),
    )
