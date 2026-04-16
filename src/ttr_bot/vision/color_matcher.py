"""Water and fish-shadow color detection for TTR ponds."""

from __future__ import annotations

import cv2
import numpy as np

from ttr_bot.config import settings


def is_water_pixel_hsv(hsv_pixel: np.ndarray) -> bool:
    """Check a single HSV pixel against the water-color ranges."""
    h, s, v = int(hsv_pixel[0]), int(hsv_pixel[1]), int(hsv_pixel[2])
    h_lo, h_hi = settings.WATER_HUE_RANGE
    return h_lo <= h <= h_hi and s >= settings.WATER_SAT_MIN and v >= settings.WATER_VAL_MIN


def build_water_mask(frame_bgr: np.ndarray) -> np.ndarray:
    """Return a binary mask where water-colored pixels are 255.

    *frame_bgr* is a BGR numpy array (full screenshot or crop).
    """
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    h_lo, h_hi = settings.WATER_HUE_RANGE
    lower = np.array([h_lo, settings.WATER_SAT_MIN, settings.WATER_VAL_MIN], dtype=np.uint8)
    upper = np.array([h_hi, 255, 255], dtype=np.uint8)
    return cv2.inRange(hsv, lower, upper)


def is_water_color_bgr(b: int, g: int, r: int) -> bool:
    """Quick BGR check: water is teal/cyan – G and B dominate R."""
    avg_bg = (int(b) + int(g)) / 2
    if avg_bg < 60:
        return False
    if int(r) > avg_bg:
        return False
    brightness = (int(r) + int(g) + int(b)) / 3
    return brightness > 40


def is_shadow_pixel_bgr(b: int, g: int, r: int) -> bool:
    """Check if a BGR pixel looks like a fish shadow.

    Shadows are darker than water but still have a blue/green tint.
    """
    brightness = (int(r) + int(g) + int(b)) / 3
    if brightness > settings.SHADOW_BRIGHTNESS_MAX:
        return False
    bg_avg = (int(b) + int(g)) / 2
    return (bg_avg - int(r)) >= settings.SHADOW_BLUE_GREEN_BIAS


def build_shadow_mask(frame_bgr: np.ndarray) -> np.ndarray:
    """Return a binary mask where fish-shadow-colored pixels are 255."""
    b, g, r = cv2.split(frame_bgr)
    b = b.astype(np.int16)
    g = g.astype(np.int16)
    r = r.astype(np.int16)

    brightness = (r + g + b) // 3
    bg_avg = (b + g) // 2

    mask = (
        (brightness <= settings.SHADOW_BRIGHTNESS_MAX)
        & ((bg_avg - r) >= settings.SHADOW_BLUE_GREEN_BIAS)
        & (brightness > 20)  # reject pure black
    )
    return (mask.astype(np.uint8) * 255)


def build_relative_shadow_mask(frame_bgr: np.ndarray, water_mask: np.ndarray) -> np.ndarray:
    """Detect fish shadows as locally-dark spots within the water.

    Uses a large Gaussian blur as a local brightness reference, then finds
    pixels significantly darker than their local neighbourhood.  This handles
    ponds with brightness gradients (e.g. dark DDL water).
    """
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

    water_pixels = gray[water_mask > 0]
    if len(water_pixels) == 0:
        return np.zeros(gray.shape, dtype=np.uint8)

    erode_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
    interior_water = cv2.erode(water_mask, erode_kernel, iterations=1)

    water_median = float(np.median(water_pixels))
    filled = gray.copy()
    filled[interior_water == 0] = np.uint8(water_median)

    local_avg = cv2.GaussianBlur(filled, (0, 0), sigmaX=30)

    diff = local_avg.astype(np.int16) - gray.astype(np.int16)
    dark_mask = (diff >= 12).astype(np.uint8) * 255

    return cv2.bitwise_and(dark_mask, interior_water)


def average_water_brightness(frame_bgr: np.ndarray, water_mask: np.ndarray) -> int:
    """Compute the average brightness of water pixels."""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    water_pixels = gray[water_mask > 0]
    if len(water_pixels) == 0:
        return 100  # sensible default
    return int(np.mean(water_pixels))
