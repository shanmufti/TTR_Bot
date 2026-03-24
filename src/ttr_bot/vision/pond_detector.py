"""Dynamic pond area detection from a game screenshot."""

from __future__ import annotations

from typing import NamedTuple

import cv2
import numpy as np

from ttr_bot.config import settings
from ttr_bot.vision.color_matcher import build_water_mask
from ttr_bot.utils.logger import log


class PondArea(NamedTuple):
    x: int
    y: int
    width: int
    height: int

    @property
    def empty(self) -> bool:
        return self.width <= 0 or self.height <= 0


EMPTY_POND = PondArea(0, 0, 0, 0)


def detect_pond(frame_bgr: np.ndarray) -> PondArea:
    """Detect the pond / water region in a full game screenshot.

    Returns the bounding rectangle of the water area, excluding UI margins.
    Ported from FishShadowAnalyzer.DetectPondArea in the reference C# bot.
    """
    h, w = frame_bgr.shape[:2]
    top = settings.POND_TOP_MARGIN
    bottom = h - settings.POND_BOTTOM_MARGIN
    left = settings.POND_SIDE_MARGIN
    right = w - settings.POND_SIDE_MARGIN

    if bottom <= top or right <= left:
        log.warning("detect_pond: frame too small for margins (%dx%d)", w, h)
        return EMPTY_POND

    cropped = frame_bgr[top:bottom, left:right]
    water_mask = build_water_mask(cropped)

    water_count = int(cv2.countNonZero(water_mask))
    if water_count < settings.POND_MIN_WATER_PIXELS:
        log.warning("detect_pond: insufficient water pixels (%d)", water_count)
        return EMPTY_POND

    coords = cv2.findNonZero(water_mask)
    if coords is None:
        return EMPTY_POND

    rx, ry, rw, rh = cv2.boundingRect(coords)

    # Map back to full-frame coordinates and add padding
    pad = settings.POND_PADDING
    px = max(left, left + rx - pad)
    py = max(top, top + ry - pad)
    pw = min(right - px, rw + 2 * pad)
    ph = min(bottom - py, rh + 2 * pad)

    pond = PondArea(px, py, pw, ph)
    log.debug("detect_pond: %s  (%d water pixels)", pond, water_count)
    return pond
