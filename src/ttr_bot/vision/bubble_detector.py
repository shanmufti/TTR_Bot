"""Bubble detection above fish shadow positions.

Fish in TTR have white/light bubbles rising above their shadow.
Ported from FishShadowAnalyzer.HasBubblesAbove in the reference C# bot.
"""

from __future__ import annotations

import numpy as np

from ttr_bot.config import settings
from ttr_bot.vision.color_matcher import average_water_brightness, build_water_mask
from ttr_bot.utils.logger import log


def has_bubbles_above(
    frame_bgr: np.ndarray,
    shadow_cx: int,
    shadow_cy: int,
    avg_water_bright: int | None = None,
) -> bool:
    """Check for bubbles in a rectangular area above a shadow position.

    Returns True if enough bright, neutral-colored pixels are found
    above the shadow center, confirming a fish is present.
    """
    h, w = frame_bgr.shape[:2]

    if avg_water_bright is None:
        water_mask = build_water_mask(frame_bgr)
        avg_water_bright = average_water_brightness(frame_bgr, water_mask)

    bubble_threshold = max(
        avg_water_bright + settings.BUBBLE_BRIGHTNESS_OFFSET,
        settings.BUBBLE_BRIGHTNESS_MIN,
    )

    half_w = settings.BUBBLE_SCAN_WIDTH // 2
    start_x = max(0, shadow_cx - half_w)
    end_x = min(w, shadow_cx + half_w)
    start_y = max(0, shadow_cy - settings.BUBBLE_SCAN_HEIGHT)
    end_y = max(0, shadow_cy - 10)

    if start_y >= end_y or start_x >= end_x:
        return False

    region = frame_bgr[start_y:end_y, start_x:end_x]
    step = settings.BUBBLE_SCAN_STEP

    bubble_count = 0
    for y in range(0, region.shape[0], step):
        for x in range(0, region.shape[1], step):
            b_val, g_val, r_val = int(region[y, x, 0]), int(region[y, x, 1]), int(region[y, x, 2])
            brightness = (r_val + g_val + b_val) // 3

            if brightness < bubble_threshold:
                continue

            # Bubbles are roughly white/neutral – channels should be close
            max_diff = max(abs(r_val - g_val), abs(g_val - b_val), abs(r_val - b_val))
            if max_diff < settings.BUBBLE_MAX_COLOR_DIFF:
                bubble_count += 1

    found = bubble_count >= settings.BUBBLE_MIN_PIXELS
    log.debug(
        "bubble_check at (%d,%d): %d bubble px (threshold=%d, need=%d) → %s",
        shadow_cx, shadow_cy, bubble_count, bubble_threshold,
        settings.BUBBLE_MIN_PIXELS, "FOUND" if found else "none",
    )
    return found
