"""Fish shadow detection via blob analysis.

Ported from FishShadowAnalyzer.cs in the reference C# bot,
rewritten to use cv2.connectedComponents for performance on Retina displays.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import cv2
import numpy as np

from ttr_bot.config import settings
from ttr_bot.vision.color_matcher import build_water_mask, build_relative_shadow_mask
from ttr_bot.vision.pond_detector import PondArea
from ttr_bot.utils.logger import log


class FishCandidate(NamedTuple):
    cx: int           # center x (window-relative)
    cy: int           # center y (window-relative)
    size: int         # blob pixel count
    score: float      # confidence 0-1
    has_bubbles: bool  # bubble confirmation


SHADOW_MIN_AREA = 100
SHADOW_MAX_AREA = 8000

_RING_OFFSETS = np.array(
    [
        (int(settings.SHADOW_WATER_CHECK_RADIUS * math.cos(math.radians(a))),
         int(settings.SHADOW_WATER_CHECK_RADIUS * math.sin(math.radians(a))))
        for a in range(0, 360, 30)
    ],
    dtype=np.int32,
)


def _is_surrounded_by_water(
    water_mask: np.ndarray, cx: int, cy: int,
) -> bool:
    """Check if a blob center is surrounded by water using pre-built water_mask."""
    h, w = water_mask.shape[:2]
    coords = _RING_OFFSETS + np.array([cx, cy], dtype=np.int32)
    valid = (
        (coords[:, 0] >= 0) & (coords[:, 0] < w)
        & (coords[:, 1] >= 0) & (coords[:, 1] < h)
    )
    if not np.any(valid):
        return False
    xs = coords[valid, 0]
    ys = coords[valid, 1]
    water_count = int(np.count_nonzero(water_mask[ys, xs]))
    return water_count / len(xs) >= settings.SHADOW_WATER_MIN_RATIO


def _filter_blob(
    label_id: int,
    stats: np.ndarray,
    centroids: np.ndarray,
    water_mask: np.ndarray,
    frame_bgr: np.ndarray,
    inner_x: int,
    inner_y: int,
    avg_water_bright: int,
    rejected: dict[str, int],
) -> FishCandidate | None:
    """Evaluate a single connected-component blob; return a candidate or None."""
    from ttr_bot.vision.bubble_detector import has_bubbles_above

    area = stats[label_id, cv2.CC_STAT_AREA]
    if area < SHADOW_MIN_AREA or area > SHADOW_MAX_AREA:
        rejected["area"] += 1
        return None

    bw = stats[label_id, cv2.CC_STAT_WIDTH]
    bh = stats[label_id, cv2.CC_STAT_HEIGHT]
    if bw < settings.SHADOW_MIN_SIZE or bh < settings.SHADOW_MIN_SIZE:
        rejected["size"] += 1
        return None

    if bw == 0 or bh == 0:
        return None
    aspect = bw / bh
    if aspect < settings.SHADOW_MIN_ASPECT or aspect > settings.SHADOW_MAX_ASPECT:
        rejected["aspect"] += 1
        return None

    fill = area / max(1, bw * bh)
    if fill < settings.SHADOW_MIN_FILL:
        rejected["fill"] += 1
        return None

    blob_cx = int(centroids[label_id][0])
    blob_cy = int(centroids[label_id][1])
    frame_cx = inner_x + blob_cx
    frame_cy = inner_y + blob_cy

    if not _is_surrounded_by_water(water_mask, blob_cx, blob_cy):
        rejected["water"] += 1
        return None

    bubbles = has_bubbles_above(frame_bgr, frame_cx, frame_cy, avg_water_bright)
    score = min(1.0, fill * (area / 500.0))
    log.info(
        "  shadow candidate: (%d,%d) area=%d %dx%d aspect=%.1f fill=%.2f score=%.2f bubbles=%s",
        frame_cx, frame_cy, area, bw, bh, aspect, fill, score, bubbles,
    )
    return FishCandidate(frame_cx, frame_cy, area, score, bubbles)


def detect_fish_shadows(
    frame_bgr: np.ndarray,
    pond: PondArea,
    avg_water_bright: int = 100,
) -> list[FishCandidate]:
    """Scan the pond region for fish shadow blobs.

    Uses cv2.connectedComponentsWithStats for O(n) clustering instead of BFS.
    Shadows are constrained to only appear within the water mask.

    *avg_water_bright* is passed through to bubble detection — compute it once
    at session start via ``color_matcher.average_water_brightness``.

    Returns a list of FishCandidate sorted by size (largest first).
    """
    if pond.empty:
        return []

    margin_x = pond.width * 15 // 100
    margin_y = pond.height * 20 // 100
    inner_x = pond.x + margin_x
    inner_y = pond.y + margin_y
    inner_w = pond.width - 2 * margin_x
    inner_h = pond.height - 2 * margin_y
    if inner_w <= 0 or inner_h <= 0:
        return []

    crop = frame_bgr[inner_y : inner_y + inner_h, inner_x : inner_x + inner_w]

    water_mask = build_water_mask(crop)
    combined = build_relative_shadow_mask(crop, water_mask)

    open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, open_kernel)

    num_labels, _labels, stats, centroids = cv2.connectedComponentsWithStats(
        combined, connectivity=8
    )

    rejected: dict[str, int] = {"area": 0, "size": 0, "aspect": 0, "fill": 0, "water": 0}
    candidates: list[FishCandidate] = [
        c
        for label_id in range(1, num_labels)
        if (c := _filter_blob(
            label_id, stats, centroids, water_mask,
            frame_bgr, inner_x, inner_y, avg_water_bright, rejected,
        )) is not None
    ]

    candidates.sort(key=lambda c: c.size, reverse=True)
    log.info(
        "detect_fish_shadows: %d candidates, %d labels, rejected: %s",
        len(candidates), num_labels - 1, rejected,
    )
    return candidates


_BUBBLE_SCORE_BOOST = 0.5


def find_best_fish(
    frame_bgr: np.ndarray,
    pond: PondArea,
    avg_water_bright: int = 100,
) -> tuple[int, int] | None:
    """Return (x, y) of the best fish shadow, or None if nothing found.

    Scoring combines reachability (prefer closer / centred) with a
    bubble-confirmation bonus so that actively-bubbling shadows beat
    bare dark spots.
    """
    candidates = detect_fish_shadows(frame_bgr, pond, avg_water_bright)
    if not candidates:
        log.info("find_best_fish: no shadows found")
        return None

    pond_cx = pond.x + pond.width // 2

    def _combined_score(c: FishCandidate) -> float:
        fwd_frac = 1.0 - (c.cy - pond.y) / max(1, pond.height)
        horiz_frac = abs(c.cx - pond_cx) / max(1, pond.width // 2)
        reachability = fwd_frac * 0.6 + horiz_frac * 0.4
        bubble_bonus = _BUBBLE_SCORE_BOOST if c.has_bubbles else 0.0
        return reachability + bubble_bonus

    candidates.sort(key=_combined_score, reverse=True)
    best = candidates[0]
    log.info(
        "find_best_fish: picking (%d,%d) size=%d score=%.2f bubbles=%s  (pond %dx%d at %d,%d)",
        best.cx, best.cy, best.size, best.score, best.has_bubbles,
        pond.width, pond.height, pond.x, pond.y,
    )
    return (best.cx, best.cy)
