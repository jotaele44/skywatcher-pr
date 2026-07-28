"""
Zone preprocessing, and the coordinate contract that comes with it.

The risk this file guards: preprocessing upscales the crop before Tesseract
sees it, so word boxes come back in scaled coordinates. Divide the factor out
and pin geometry is right; forget to and every coordinate is silently doubled —
nothing raises, the affine geocoder fits the wrong points, and the error only
shows up as bad lat/lon much later.
"""
from __future__ import annotations

from PIL import Image

from fr24.rlsm_preprocess import MODES, otsu_threshold, preprocess, scale_for
from fr24.rlsm_wordboxes import words_from_tesseract_data
from fr24.rlsm_zones import ZONE_OCR_CONFIG


def _synthetic(bg: int, ink: int, size=(60, 24)) -> Image.Image:
    """A crop with a small block of 'text' — the minority pixel class."""
    img = Image.new("RGB", size, (bg, bg, bg))
    for y in range(8, 16):
        for x in range(6, 26):
            img.putpixel((x, y), (ink, ink, ink))
    return img


class TestPreprocess:
    def test_none_is_identity(self):
        crop = _synthetic(20, 240)
        assert preprocess(crop, "none") is crop

    def test_unknown_mode_passes_through(self):
        crop = _synthetic(20, 240)
        assert preprocess(crop, "not_a_mode") is crop

    def test_modes_upscale_and_binarize(self):
        crop = _synthetic(20, 240)
        for mode in ("high_contrast", "label_mask"):
            out = preprocess(crop, mode, 2.0)
            assert out.mode == "L"
            assert out.size == (crop.width * 2, crop.height * 2)
            hist = out.histogram()
            assert hist[0] + hist[255] == out.width * out.height, "output must be binary"

    def test_polarity_light_text_on_dark(self):
        # Light glyphs on a dark basemap must come out dark-on-light for Tesseract.
        out = preprocess(_synthetic(20, 240), "high_contrast", 1.0)
        hist = out.histogram()
        assert hist[0] < hist[255], "ink should be the minority (dark) class"

    def test_polarity_dark_text_on_light(self):
        # The light basemap draws dark labels; same output orientation.
        out = preprocess(_synthetic(240, 20), "high_contrast", 1.0)
        hist = out.histogram()
        assert hist[0] < hist[255]

    def test_otsu_handles_empty_histogram(self):
        assert otsu_threshold([0] * 256) == 128

    def test_scale_for_matches_mode_default(self):
        assert scale_for("high_contrast") == 2.0
        assert scale_for("none") == 1.0
        assert scale_for("high_contrast", 3.0) == 3.0


class TestWordBoxScaleContract:
    DATA = {"text": ["SAN", "JUAN"], "conf": [90, 90],
            "left": [200, 400], "top": [100, 100],
            "width": [100, 100], "height": [40, 40]}

    def test_scale_one_is_offset_only(self):
        out = words_from_tesseract_data(self.DATA, x_off=0, y_off=126, scale=1.0)
        assert (out[0]["x"], out[0]["y"]) == (200, 226)

    def test_scale_divides_before_offset(self):
        # 100 / 2 + 126 = 176 — the offset is in source pixels, not scaled ones.
        out = words_from_tesseract_data(self.DATA, x_off=0, y_off=126, scale=2.0)
        assert (out[0]["x"], out[0]["y"], out[0]["w"], out[0]["h"]) == (100, 176, 50, 20)

    def test_default_scale_is_backwards_compatible(self):
        assert words_from_tesseract_data(self.DATA, x_off=0, y_off=0) == \
               words_from_tesseract_data(self.DATA, x_off=0, y_off=0, scale=1.0)

    def test_zero_scale_does_not_divide_by_zero(self):
        out = words_from_tesseract_data(self.DATA, scale=0.0)
        assert out[0]["x"] == 200


class TestRunnerScalePlumbing:
    """
    The contract above, one layer up — at the seam where it actually broke.

    ``TestWordBoxScaleContract`` pins the arithmetic inside
    ``words_from_tesseract_data``, and passed even while the parallel runner —
    the path that processes the whole corpus — called it without a ``scale`` at
    all. Every zone declares ``scale: 2.0``, so each stored word box was landing
    at twice its true coordinate. Testing the helper in isolation could never
    catch that; only calling the runner can.
    """

    DATA = {"text": ["SAN", "JUAN"], "conf": [90, 90],
            "left": [200, 400], "top": [100, 100],
            "width": [100, 100], "height": [40, 40]}

    def _patched(self, monkeypatch, module):
        """Stub image_to_data so no Tesseract binary is needed in CI."""
        monkeypatch.setattr(module, "preprocess", lambda crop, mode, scale: crop)

        class _Stub:
            Output = type("Output", (), {"DICT": "dict"})

            @staticmethod
            def image_to_data(img, config="", output_type=None):
                return TestRunnerScalePlumbing.DATA

        monkeypatch.setattr(module, "pytesseract", _Stub)

    def test_parallel_runner_divides_the_upscale_out(self, monkeypatch):
        from fr24 import rlsm_ocr_parallel as mod

        self._patched(monkeypatch, mod)
        _, boxes, *_ = mod._ocr_with_conf(_synthetic(20, 240), "--psm 11",
                                          x_off=0, y_off=126,
                                          mode="label_mask", scale=2.0)
        # 200/2 + 0 = 100, 100/2 + 126 = 176 — source pixels, not scaled ones.
        assert (boxes[0]["x"], boxes[0]["y"]) == (100, 176)
        assert (boxes[0]["w"], boxes[0]["h"]) == (50, 20)

    def test_serial_runner_divides_the_upscale_out(self, monkeypatch):
        from fr24 import rlsm_ocr as mod
        from fr24.rlsm_zones import zones_for

        self._patched(monkeypatch, mod)
        zone = next(z for z in zones_for(1170, 2532) if z.name == "label_layer")
        _, boxes, *_ = mod._ocr_zone(_synthetic(20, 240), zone, "--psm 11",
                                     mode="label_mask", scale=2.0)
        assert (boxes[0]["x"], boxes[0]["y"]) == (100 + zone.x, 50 + zone.y)

    def test_mode_none_leaves_coordinates_alone(self, monkeypatch):
        # No upscale happened, so nothing may be divided out even if a stale
        # scale is still sitting in the zone config.
        from fr24 import rlsm_ocr_parallel as mod

        self._patched(monkeypatch, mod)
        _, boxes, *_ = mod._ocr_with_conf(_synthetic(20, 240), "--psm 11",
                                          mode="none", scale=2.0)
        assert (boxes[0]["x"], boxes[0]["y"]) == (200, 100)


class TestZoneConfig:
    def test_every_zone_declares_a_known_mode_and_scale(self):
        for zone, cfg in ZONE_OCR_CONFIG.items():
            assert cfg["preprocess"] in MODES, f"{zone} declares an unknown mode"
            assert cfg["scale"] >= 1.0, f"{zone} must declare the upscale it uses"

    def test_label_layer_is_preprocessed_at_all(self):
        # The bench cannot separate label_mask from high_contrast at n=22, so
        # this asserts the thing it *can* support: the map label layer is not
        # sent to Tesseract raw. Changing the mode means re-running
        # scripts/rlsm_ocr_bench.py, not guessing.
        assert ZONE_OCR_CONFIG["label_layer"]["preprocess"] != "none"
        assert ZONE_OCR_CONFIG["label_layer"]["preprocess"] == "label_mask"
