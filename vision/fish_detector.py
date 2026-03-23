"""Fish shadow detection via blob analysis.

Ported from FishShadowAnalyzer.cs in the reference C# bot,
rewritten to use cv2.connectedComponents for performance on Retina displays.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import cv2
import numpy as np

from config import settings
from vision.color_matcher import build_water_mask, build_relative_shadow_mask, is_water_color_bgr
from vision.pond_detector import PondArea
from utils.logger import log


class FishCandidate(NamedTuple):
    cx: int      # center x (window-relative)
    cy: int      # center y (window-relative)
    size: int    # blob pixel count
    score: float # confidence 0-1


SHADOW_MIN_AREA = 100
SHADOW_MAX_AREA = 8000


def _is_surrounded_by_water(
    frame_bgr: np.ndarray, cx: int, cy: int, radius: int = settings.SHADOW_WATER_CHECK_RADIUS
) -> bool:
    """Check if a blob center is surrounded by water-colored pixels."""
    h, w = frame_bgr.shape[:2]
    water_count = 0
    total = 0

    for angle_deg in range(0, 360, 30):
        rad = math.radians(angle_deg)
        check_x = int(cx + radius * math.cos(rad))
        check_y = int(cy + radius * math.sin(rad))
        if 0 <= check_x < w and 0 <= check_y < h:
            total += 1
            b, g, r = frame_bgr[check_y, check_x]
            if is_water_color_bgr(int(b), int(g), int(r)):
                water_count += 1

    if total == 0:
        return False
    ratio = water_count / total
    return ratio >= settings.SHADOW_WATER_MIN_RATIO


def detect_fish_shadows(frame_bgr: np.ndarray, pond: PondArea) -> list[FishCandidate]:
    """Scan the pond region for fish shadow blobs.

    Uses cv2.connectedComponentsWithStats for O(n) clustering instead of BFS.
    Shadows are constrained to only appear within the water mask.
    Returns a list of FishCandidate sorted by size (largest first).
    """
    if pond.empty:
        return []

    # Restrict to the central 70% of the pond to avoid edge artifacts
    # (dock posts, lamps, signs, UI elements near pond borders).
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

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        combined, connectivity=8
    )

    candidates: list[FishCandidate] = []
    rejected = {"area": 0, "size": 0, "aspect": 0, "fill": 0, "water": 0}
    for label_id in range(1, num_labels):
        area = stats[label_id, cv2.CC_STAT_AREA]
        if area < SHADOW_MIN_AREA or area > SHADOW_MAX_AREA:
            rejected["area"] += 1
            continue

        bw = stats[label_id, cv2.CC_STAT_WIDTH]
        bh = stats[label_id, cv2.CC_STAT_HEIGHT]
        if bw < settings.SHADOW_MIN_SIZE or bh < settings.SHADOW_MIN_SIZE:
            rejected["size"] += 1
            continue

        if bw == 0 or bh == 0:
            continue
        aspect = bw / bh
        if aspect < settings.SHADOW_MIN_ASPECT or aspect > settings.SHADOW_MAX_ASPECT:
            rejected["aspect"] += 1
            continue

        fill = area / max(1, bw * bh)
        if fill < settings.SHADOW_MIN_FILL:
            rejected["fill"] += 1
            continue

        blob_cx = int(centroids[label_id][0])
        blob_cy = int(centroids[label_id][1])
        frame_cx = inner_x + blob_cx
        frame_cy = inner_y + blob_cy

        if not _is_surrounded_by_water(frame_bgr, frame_cx, frame_cy):
            rejected["water"] += 1
            continue

        score = min(1.0, fill * (area / 500.0))
        candidates.append(FishCandidate(frame_cx, frame_cy, area, score))
        log.info(
            "  shadow candidate: (%d,%d) area=%d %dx%d aspect=%.1f fill=%.2f score=%.2f",
            frame_cx, frame_cy, area, bw, bh, aspect, fill, score,
        )

    candidates.sort(key=lambda c: c.size, reverse=True)
    log.info(
        "detect_fish_shadows: %d candidates, %d labels, rejected: %s",
        len(candidates), num_labels - 1, rejected,
    )
    return candidates


def find_best_fish(frame_bgr: np.ndarray, pond: PondArea) -> tuple[int, int] | None:
    """Return (x, y) of the best fish shadow, or None if nothing found.

    Prefers shadows closer to the toon (bottom of pond) so the bobber
    reaches them faster and with higher accuracy.
    """
    candidates = detect_fish_shadows(frame_bgr, pond)
    if not candidates:
        log.info("find_best_fish: no shadows found")
        return None

    pond_cx = pond.x + pond.width // 2

    def _reachability(c: FishCandidate) -> float:
        fwd_frac = 1.0 - (c.cy - pond.y) / max(1, pond.height)
        horiz_frac = abs(c.cx - pond_cx) / max(1, pond.width // 2)
        return fwd_frac * 0.6 + horiz_frac * 0.4

    candidates.sort(key=_reachability)
    best = candidates[0]
    log.info(
        "find_best_fish: picking (%d,%d) size=%d score=%.2f  (pond %dx%d at %d,%d)",
        best.cx, best.cy, best.size, best.score,
        pond.width, pond.height, pond.x, pond.y,
    )
    return (best.cx, best.cy)
