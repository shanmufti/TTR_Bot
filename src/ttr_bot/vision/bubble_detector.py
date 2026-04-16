"""Bubble detection above fish shadow positions.

Fish in TTR have white/light bubbles rising above their shadow.
Ported from FishShadowAnalyzer.HasBubblesAbove in the reference C# bot,
rewritten with vectorized numpy ops for speed.
"""

from __future__ import annotations

import numpy as np

from ttr_bot.config import settings
from ttr_bot.utils.logger import log


def has_bubbles_above(
    frame_bgr: np.ndarray,
    shadow_cx: int,
    shadow_cy: int,
    avg_water_bright: int = 100,
) -> bool:
    """Check for bubbles in a rectangular area above a shadow position.

    Bubbles are bright, roughly white/neutral pixels above the shadow.
    Uses fully vectorized numpy — no Python pixel loops.

    *avg_water_bright* should be pre-computed once per session via
    ``color_matcher.average_water_brightness``.
    """
    _, w = frame_bgr.shape[:2]

    bubble_threshold = max(
        avg_water_bright + settings.BUBBLE_BRIGHTNESS_OFFSET,
        settings.BUBBLE_BRIGHTNESS_MIN,
    )

    half_w = settings.BUBBLE_SCAN_WIDTH // 2
    x0 = max(0, shadow_cx - half_w)
    x1 = min(w, shadow_cx + half_w)
    y0 = max(0, shadow_cy - settings.BUBBLE_SCAN_HEIGHT)
    y1 = max(0, shadow_cy - 10)

    if y0 >= y1 or x0 >= x1:
        return False

    region = frame_bgr[y0:y1, x0:x1]

    brightness = region.mean(axis=2)
    spread = region.max(axis=2).astype(np.int16) - region.min(axis=2).astype(np.int16)

    bubble_mask = (brightness >= bubble_threshold) & (spread <= settings.BUBBLE_MAX_COLOR_DIFF)
    count = int(np.count_nonzero(bubble_mask))

    found = count >= settings.BUBBLE_MIN_PIXELS
    log.debug(
        "bubble_check at (%d,%d): %d bubble px (threshold=%d, need=%d) -> %s",
        shadow_cx,
        shadow_cy,
        count,
        bubble_threshold,
        settings.BUBBLE_MIN_PIXELS,
        "FOUND" if found else "none",
    )
    return found
