"""Dynamic pond area detection from a game screenshot."""

from __future__ import annotations

from typing import NamedTuple

import cv2
import numpy as np

from ttr_bot.config import settings
from ttr_bot.utils.logger import log
from ttr_bot.vision.color_matcher import build_water_mask


class PondArea(NamedTuple):
    """Axis-aligned bounding rectangle of the detected pond water."""

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

    The fishing dock view has: sky (top ~20%), pond water (middle ~40%),
    dock/toon/UI (bottom ~30%), side docks (edges).  We crop to the pond
    zone, then find the densest horizontal band of water to lock onto the
    actual pond surface (excluding sky which has similar HSV to water).
    """
    h, w = frame_bgr.shape[:2]

    top = int(h * 0.18)
    bottom = int(h * 0.72)
    left = int(w * 0.10)
    right = int(w * 0.90)

    if bottom <= top or right <= left:
        log.warning("detect_pond: frame too small (%dx%d)", w, h)
        return EMPTY_POND

    cropped = frame_bgr[top:bottom, left:right]
    water_mask = build_water_mask(cropped)

    water_count = int(cv2.countNonZero(water_mask))
    if water_count < settings.POND_MIN_WATER_PIXELS:
        log.warning("detect_pond: insufficient water pixels (%d)", water_count)
        return EMPTY_POND

    _ch, cw = water_mask.shape

    row_density = np.count_nonzero(water_mask, axis=1).astype(np.float64)
    row_density = cv2.GaussianBlur(row_density.reshape(-1, 1), (1, 31), 0).flatten()

    threshold = cw * 0.50
    water_rows = np.where(row_density >= threshold)[0]
    if len(water_rows) == 0:
        log.warning("detect_pond: no dense water rows found")
        return EMPTY_POND

    ry_top = int(water_rows[0])
    ry_bot = int(water_rows[-1])

    row_slice = water_mask[ry_top : ry_bot + 1, :]
    col_density = np.count_nonzero(row_slice, axis=0)
    water_cols = np.where(col_density >= (ry_bot - ry_top) * 0.30)[0]
    if len(water_cols) == 0:
        rx_left, rx_right = 0, cw
    else:
        rx_left = int(water_cols[0])
        rx_right = int(water_cols[-1])

    pad = settings.POND_PADDING
    px = max(0, left + rx_left - pad)
    py = max(0, top + ry_top - pad)
    pw = min(w - px, (rx_right - rx_left) + 2 * pad)
    ph = min(h - py, (ry_bot - ry_top) + 2 * pad)

    pond = PondArea(px, py, pw, ph)
    log.debug(
        "detect_pond: %s  (%d water px, dense rows %d-%d)", pond, water_count, ry_top, ry_bot
    )
    return pond
