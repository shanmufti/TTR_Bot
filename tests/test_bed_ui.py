"""Tests for the garden bed UI classification module."""

from unittest.mock import patch

import numpy as np

from ttr_bot.gardening.bed_ui import (
    BED_BUTTON_NAMES,
    classify_bed_state,
    detect_bed_button,
)
from ttr_bot.vision.template_matcher import MatchResult


def _make_match(confidence: float = 0.9) -> MatchResult:
    return MatchResult(x=100, y=100, confidence=confidence, width=50, height=50)


_DUMMY_FRAME = np.zeros((100, 100, 3), dtype=np.uint8)


class TestDetectBedButton:
    @patch("ttr_bot.gardening.bed_ui.tm.find_template", return_value=None)
    def test_no_match_returns_none(self, mock_find):
        assert detect_bed_button(_DUMMY_FRAME) is None

    @patch("ttr_bot.gardening.bed_ui.tm.find_template")
    def test_first_match_wins(self, mock_find):
        def side_effect(frame, name, **kwargs):
            if name == "remove_button":
                return _make_match()
            return None

        mock_find.side_effect = side_effect
        result = detect_bed_button(_DUMMY_FRAME)
        assert result == "remove_button"

    def test_bed_button_names_is_tuple(self):
        assert isinstance(BED_BUTTON_NAMES, tuple)
        assert len(BED_BUTTON_NAMES) >= 3


class TestClassifyBedState:
    @patch("ttr_bot.gardening.bed_ui.tm.find_template")
    def test_plant_button_returns_plant(self, mock_find):
        def side_effect(frame, name, **kwargs):
            if name == "plant_flower_button":
                return _make_match(0.90)
            return None

        mock_find.side_effect = side_effect
        assert classify_bed_state(_DUMMY_FRAME) == "plant"

    @patch("ttr_bot.gardening.bed_ui.tm.find_template")
    def test_pick_button_returns_pick(self, mock_find):
        def side_effect(frame, name, **kwargs):
            if name == "pick_flower_button":
                return _make_match(0.90)
            return None

        mock_find.side_effect = side_effect
        assert classify_bed_state(_DUMMY_FRAME) == "pick"

    @patch("ttr_bot.gardening.bed_ui.tm.find_template")
    def test_remove_button_returns_pick(self, mock_find):
        def side_effect(frame, name, **kwargs):
            if name == "remove_button":
                return _make_match(0.90)
            return None

        mock_find.side_effect = side_effect
        assert classify_bed_state(_DUMMY_FRAME) == "pick"

    @patch("ttr_bot.gardening.bed_ui.tm.find_template", return_value=None)
    def test_no_match_returns_unknown(self, mock_find):
        assert classify_bed_state(_DUMMY_FRAME) == "unknown"
