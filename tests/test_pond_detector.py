"""Tests for the pond detection module."""

from __future__ import annotations

import numpy as np

from ttr_bot.vision.pond_detector import EMPTY_POND, PondArea, detect_pond


class TestPondArea:
    def test_empty_property(self):
        assert PondArea(0, 0, 0, 0).empty is True
        assert PondArea(10, 10, 0, 50).empty is True
        assert PondArea(10, 10, 50, 0).empty is True

    def test_non_empty(self):
        assert PondArea(10, 10, 100, 100).empty is False

    def test_empty_pond_sentinel(self):
        assert EMPTY_POND.empty is True


class TestDetectPond:
    def test_detects_water_band(self, pond_scene_frame):
        pond = detect_pond(pond_scene_frame)
        assert not pond.empty
        assert pond.width > 0
        assert pond.height > 0

    def test_dark_frame_returns_empty(self, dark_frame):
        pond = detect_pond(dark_frame)
        assert pond.empty

    def test_tiny_frame_returns_empty(self):
        tiny = np.zeros((10, 10, 3), dtype=np.uint8)
        pond = detect_pond(tiny)
        assert pond.empty

    def test_pond_within_frame_bounds(self, pond_scene_frame):
        h, w = pond_scene_frame.shape[:2]
        pond = detect_pond(pond_scene_frame)
        if not pond.empty:
            assert pond.x >= 0
            assert pond.y >= 0
            assert pond.x + pond.width <= w
            assert pond.y + pond.height <= h
