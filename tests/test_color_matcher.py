"""Tests for the water / shadow color detection module."""

import numpy as np

from ttr_bot.vision.color_matcher import (
    average_water_brightness,
    build_water_mask,
    is_shadow_pixel_bgr,
    is_water_color_bgr,
    is_water_pixel_hsv,
)


class TestIsWaterPixelHSV:
    def test_teal_pixel_is_water(self):
        hsv = np.array([90, 180, 160], dtype=np.uint8)
        assert is_water_pixel_hsv(hsv) is True

    def test_red_pixel_is_not_water(self):
        hsv = np.array([10, 200, 200], dtype=np.uint8)
        assert is_water_pixel_hsv(hsv) is False

    def test_desaturated_pixel_is_not_water(self):
        hsv = np.array([90, 10, 160], dtype=np.uint8)
        assert is_water_pixel_hsv(hsv) is False

    def test_dark_pixel_is_not_water(self):
        hsv = np.array([90, 180, 10], dtype=np.uint8)
        assert is_water_pixel_hsv(hsv) is False


class TestIsWaterColorBGR:
    def test_teal_is_water(self):
        assert is_water_color_bgr(200, 160, 60) is True

    def test_red_is_not_water(self):
        assert is_water_color_bgr(30, 30, 200) is False

    def test_black_is_not_water(self):
        assert is_water_color_bgr(0, 0, 0) is False


class TestIsShadowPixelBGR:
    def test_dark_bluegreen_is_shadow(self):
        assert is_shadow_pixel_bgr(80, 70, 40) is True

    def test_bright_pixel_is_not_shadow(self):
        assert is_shadow_pixel_bgr(200, 200, 200) is False

    def test_red_pixel_is_not_shadow(self):
        assert is_shadow_pixel_bgr(30, 30, 80) is False


class TestBuildWaterMask:
    def test_all_water_frame(self, blue_water_frame):
        mask = build_water_mask(blue_water_frame)
        assert mask.shape == blue_water_frame.shape[:2]
        water_fraction = np.count_nonzero(mask) / mask.size
        assert water_fraction > 0.9

    def test_dark_frame_no_water(self, dark_frame):
        mask = build_water_mask(dark_frame)
        water_fraction = np.count_nonzero(mask) / mask.size
        assert water_fraction < 0.1


class TestAverageWaterBrightness:
    def test_with_water_pixels(self, blue_water_frame):
        mask = build_water_mask(blue_water_frame)
        brightness = average_water_brightness(blue_water_frame, mask)
        assert 50 < brightness < 200

    def test_empty_mask_returns_default(self, dark_frame):
        empty_mask = np.zeros(dark_frame.shape[:2], dtype=np.uint8)
        brightness = average_water_brightness(dark_frame, empty_mask)
        assert brightness == 100
