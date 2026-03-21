"""Fish shadow detection via blob analysis.

Ported from FishShadowAnalyzer.cs in the reference C# bot.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import cv2
import numpy as np

from config import settings
from vision.color_matcher import build_shadow_mask, is_water_color_bgr
from vision.pond_detector import PondArea
from utils.logger import log


class FishCandidate(NamedTuple):
    cx: int      # center x (window-relative)
    cy: int      # center y (window-relative)
    size: int    # blob pixel count
    score: float # confidence 0-1


def _find_blobs(points: list[tuple[int, int]], max_dist: int) -> list[list[tuple[int, int]]]:
    """Group nearby points into blobs using BFS clustering.

    Mirrors FishShadowAnalyzer.FindBlobs from the C# reference.
    """
    if not points:
        return []

    blobs: list[list[tuple[int, int]]] = []
    visited = set()

    for i, pt in enumerate(points):
        if i in visited:
            continue
        blob: list[tuple[int, int]] = []
        queue = [i]
        visited.add(i)

        while queue:
            cur_idx = queue.pop(0)
            blob.append(points[cur_idx])
            cx, cy = points[cur_idx]

            for j, (jx, jy) in enumerate(points):
                if j in visited:
                    continue
                if abs(cx - jx) <= max_dist and abs(cy - jy) <= max_dist:
                    dist = math.hypot(cx - jx, cy - jy)
                    if dist <= max_dist:
                        queue.append(j)
                        visited.add(j)

        if blob:
            blobs.append(blob)

    return blobs


def _is_circular_blob(blob: list[tuple[int, int]]) -> bool:
    """Check if a blob shape is roughly circular (like a fish shadow)."""
    if len(blob) < 5:
        return False

    xs = [p[0] for p in blob]
    ys = [p[1] for p in blob]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    bw = max_x - min_x
    bh = max_y - min_y

    if bw < 3 or bh < 3:
        return False

    aspect = bw / bh
    if aspect < settings.SHADOW_MIN_ASPECT or aspect > settings.SHADOW_MAX_ASPECT:
        return False

    bounding_area = bw * bh
    step = settings.SHADOW_SCAN_STEP
    fill = (len(blob) * step * step) / bounding_area
    if fill < settings.SHADOW_MIN_FILL:
        return False

    if bw < settings.SHADOW_MIN_SIZE or bh < settings.SHADOW_MIN_SIZE:
        return False

    return True


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

    Returns a list of FishCandidate sorted by size (largest first).
    """
    if pond.empty:
        return []

    crop = frame_bgr[pond.y : pond.y + pond.height, pond.x : pond.x + pond.width]
    shadow_mask = build_shadow_mask(crop)

    step = settings.SHADOW_SCAN_STEP
    shadow_points: list[tuple[int, int]] = []
    for y in range(0, crop.shape[0], step):
        for x in range(0, crop.shape[1], step):
            if shadow_mask[y, x] > 0:
                shadow_points.append((x, y))

    if not shadow_points:
        return []

    blobs = _find_blobs(shadow_points, settings.SHADOW_BLOB_MAX_DISTANCE)

    candidates: list[FishCandidate] = []
    for blob in blobs:
        if not _is_circular_blob(blob):
            continue

        xs = [p[0] for p in blob]
        ys = [p[1] for p in blob]
        blob_cx = sum(xs) // len(xs)
        blob_cy = sum(ys) // len(ys)

        # Convert back to full-frame coordinates
        frame_cx = pond.x + blob_cx
        frame_cy = pond.y + blob_cy

        if not _is_surrounded_by_water(frame_bgr, frame_cx, frame_cy):
            continue

        blob_size = len(blob)
        bw = max(xs) - min(xs)
        bh = max(ys) - min(ys)
        fill = (blob_size * step * step) / max(1, bw * bh)
        score = min(1.0, fill * (blob_size / 100.0))

        candidates.append(FishCandidate(frame_cx, frame_cy, blob_size, score))

    candidates.sort(key=lambda c: c.size, reverse=True)
    return candidates


def find_best_fish(frame_bgr: np.ndarray, pond: PondArea) -> tuple[int, int] | None:
    """Return (x, y) of the best fish shadow, or None if nothing found."""
    candidates = detect_fish_shadows(frame_bgr, pond)
    if not candidates:
        return None
    best = candidates[0]
    log.debug("find_best_fish: (%d, %d) size=%d score=%.2f", best.cx, best.cy, best.size, best.score)
    return (best.cx, best.cy)
