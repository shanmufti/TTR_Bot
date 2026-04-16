"""Fish shadow detection via blob analysis.

Detects dark oval blobs in the pond water, scores them, and picks the best
target to cast at.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import cv2
import numpy as np

from ttr_bot.config import settings
from ttr_bot.utils.logger import log
from ttr_bot.vision.color_matcher import build_water_mask
from ttr_bot.vision.pond_detector import PondArea


class FishCandidate(NamedTuple):
    """A detected fish shadow with its position, size, and ranking score."""

    cx: int
    cy: int
    size: int
    score: float
    has_bubbles: bool


SHADOW_MIN_AREA = settings.SHADOW_MIN_AREA
SHADOW_MAX_AREA = settings.SHADOW_MAX_AREA
_SHADOW_MAX_DIM = settings.SHADOW_MAX_DIM

_RING_OFFSETS = np.array(
    [
        (
            int(settings.SHADOW_WATER_CHECK_RADIUS * math.cos(math.radians(a))),
            int(settings.SHADOW_WATER_CHECK_RADIUS * math.sin(math.radians(a))),
        )
        for a in range(0, 360, 30)
    ],
    dtype=np.int32,
)


def _is_surrounded_by_water(water_mask: np.ndarray, cx: int, cy: int) -> bool:
    h, w = water_mask.shape[:2]
    coords = _RING_OFFSETS + np.array([cx, cy], dtype=np.int32)
    valid = (coords[:, 0] >= 0) & (coords[:, 0] < w) & (coords[:, 1] >= 0) & (coords[:, 1] < h)
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
    if bw > _SHADOW_MAX_DIM or bh > _SHADOW_MAX_DIM:
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
        frame_cx,
        frame_cy,
        area,
        bw,
        bh,
        aspect,
        fill,
        score,
        bubbles,
    )
    return FishCandidate(frame_cx, frame_cy, area, score, bubbles)


def detect_fish_shadows(
    frame_bgr: np.ndarray,
    pond: PondArea,
    avg_water_bright: int = 100,
) -> list[FishCandidate]:
    """Find dark-oval blobs (fish shadows) inside the pond region."""
    if pond.empty:
        return []

    margin_x = pond.width * 10 // 100
    margin_top = pond.height * 10 // 100
    margin_bot = pond.height * 40 // 100
    inner_x = pond.x + margin_x
    inner_y = pond.y + margin_top
    inner_w = pond.width - 2 * margin_x
    inner_h = pond.height - margin_top - margin_bot
    if inner_w <= 0 or inner_h <= 0:
        return []

    crop = frame_bgr[inner_y : inner_y + inner_h, inner_x : inner_x + inner_w]

    water_mask = build_water_mask(crop)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    water_pixels = gray[water_mask > 0]
    if len(water_pixels) == 0:
        return []
    water_median = float(np.median(water_pixels))

    shadow_thresh = water_median - 20
    combined = ((gray < shadow_thresh) & (water_mask > 0)).astype(np.uint8) * 255

    open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, open_kernel)

    num_labels, _labels, stats, centroids = cv2.connectedComponentsWithStats(
        combined, connectivity=8
    )

    rejected: dict[str, int] = {"area": 0, "size": 0, "aspect": 0, "fill": 0, "water": 0}
    candidates: list[FishCandidate] = [
        c
        for label_id in range(1, num_labels)
        if (
            c := _filter_blob(
                label_id,
                stats,
                centroids,
                water_mask,
                frame_bgr,
                inner_x,
                inner_y,
                avg_water_bright,
                rejected,
            )
        )
        is not None
    ]

    candidates.sort(key=lambda c: c.size, reverse=True)
    log.info(
        "detect_fish_shadows: %d candidates, %d labels, rejected: %s",
        len(candidates),
        num_labels - 1,
        rejected,
    )
    return candidates


_BUBBLE_SCORE_BOOST = settings.FISH_BUBBLE_SCORE_BOOST
_NEAR_THRESHOLD = settings.FISH_NEAR_THRESHOLD


def rank_fish(
    frame_bgr: np.ndarray,
    pond: PondArea,
    avg_water_bright: int = 100,
    *,
    candidates: list[FishCandidate] | None = None,
) -> list[tuple[int, int, float]]:
    """Return all shadow targets ranked by score: [(x, y, score), ...].

    If *candidates* is provided, skip detection and rank the given list.
    """
    if candidates is None:
        candidates = detect_fish_shadows(frame_bgr, pond, avg_water_bright)
    if not candidates:
        return []

    pond_cx = pond.x + pond.width // 2

    def _score(c: FishCandidate) -> float:
        rel_y = (c.cy - pond.y) / max(1, pond.height)
        depth = 1.0 - 2.0 * abs(rel_y - 0.35)
        centered = 1.0 - abs(c.cx - pond_cx) / max(1, pond.width // 2)
        bubble = _BUBBLE_SCORE_BOOST if c.has_bubbles else 0.0
        return c.score + max(0.0, depth) * 0.4 + centered * 0.2 + bubble

    scored = [(c.cx, c.cy, _score(c)) for c in candidates]
    scored.sort(key=lambda t: t[2], reverse=True)
    return scored


def find_best_fish(
    frame_bgr: np.ndarray,
    pond: PondArea,
    avg_water_bright: int = 100,
    *,
    avoid: tuple[int, int] | None = None,
    candidates: list[FishCandidate] | None = None,
) -> tuple[int, int] | None:
    """Return (x, y) of the best fish shadow, or None.

    If *candidates* is provided, skip detection and rank the given list.
    If *avoid* is set, skip any candidate within ``_NEAR_THRESHOLD`` px
    so the bot cycles through different shadows after a miss.
    """
    ranked = rank_fish(frame_bgr, pond, avg_water_bright, candidates=candidates)
    if not ranked:
        log.info("find_best_fish: no shadows found")
        return None

    for cx, cy, sc in ranked:
        if avoid is not None:
            dist = ((cx - avoid[0]) ** 2 + (cy - avoid[1]) ** 2) ** 0.5
            if dist < _NEAR_THRESHOLD:
                log.info("find_best_fish: skipping (%d,%d) too close to avoid target", cx, cy)
                continue
        log.info("find_best_fish: picking (%d,%d) score=%.2f", cx, cy, sc)
        return (cx, cy)

    best = ranked[0]
    log.info("find_best_fish: all near avoid — falling back to (%d,%d)", best[0], best[1])
    return (best[0], best[1])


def has_catch_popup(frame: np.ndarray) -> bool:
    """Detect the fish-caught popup by its warm-yellow card background.

    Checks the center-top region for the popup's distinctive
    cream/yellow pixels (HSV H=25-35, S=40-90, V>220).
    """
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    roi = hsv[h // 6 : h // 2, w // 4 : 3 * w // 4]
    card = (
        (roi[:, :, 0] >= 25)
        & (roi[:, :, 0] <= 35)
        & (roi[:, :, 1] >= 40)
        & (roi[:, :, 1] <= 90)
        & (roi[:, :, 2] >= 220)
    )
    return bool(np.sum(card) / card.size > 0.05)
