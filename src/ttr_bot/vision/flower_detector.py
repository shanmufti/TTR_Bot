"""Detect flowers on screen using color analysis.

Flowers are identified as saturated RED blobs adjacent to GREEN areas
(stems / grass).  This filters out the house wall and other reddish
surfaces that are not near green.

The main entry point is :func:`scan_for_flowers` which returns a list
of :class:`FlowerBlob` sorted nearest-first (lowest on screen = closest).
"""

from __future__ import annotations

from typing import NamedTuple

import cv2
import numpy as np


class FlowerBlob(NamedTuple):
    cx: int
    cy: int
    area: int
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int


# HSV ranges for red flower petals (wraps around 0/180)
# S>=120 catches distant/dim flowers; V>=150 rejects dark house walls
_RED_LO1, _RED_HI1 = (0, 120, 150), (8, 255, 255)
_RED_LO2, _RED_HI2 = (174, 120, 150), (180, 255, 255)

# HSV range for green (grass / stems)
_GREEN_LO, _GREEN_HI = (35, 50, 50), (85, 255, 255)

_GREEN_DILATE_PX = 30
_MIN_BLOB_AREA = 600
_MORPH_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))


def scan_for_flowers(
    frame: np.ndarray,
    ui_margin_left: float = 0.05,
    ui_margin_right: float = 0.05,
    ui_margin_top: float = 0.28,
    ui_margin_bottom: float = 0.25,
) -> list[FlowerBlob]:
    """Return flower blobs sorted nearest-first (largest y = closest)."""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    red = cv2.inRange(hsv, _RED_LO1, _RED_HI1) | cv2.inRange(hsv, _RED_LO2, _RED_HI2)
    green = cv2.inRange(hsv, _GREEN_LO, _GREEN_HI)
    green_near = cv2.dilate(
        green, np.ones((_GREEN_DILATE_PX, _GREEN_DILATE_PX), np.uint8)
    )

    playfield = np.zeros((h, w), np.uint8)
    y0 = int(h * ui_margin_top)
    y1 = int(h * (1 - ui_margin_bottom))
    x0 = int(w * ui_margin_left)
    x1 = int(w * (1 - ui_margin_right))
    playfield[y0:y1, x0:x1] = 255

    # Exclude center where the character stands (avoids red outfit false positives)
    char_x0 = int(w * 0.40)
    char_x1 = int(w * 0.60)
    char_y0 = int(h * 0.35)
    char_y1 = int(h * 0.85)
    playfield[char_y0:char_y1, char_x0:char_x1] = 0

    mask = red & green_near & playfield
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _MORPH_KERNEL)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _MORPH_KERNEL)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    blobs: list[FlowerBlob] = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < _MIN_BLOB_AREA:
            continue
        bx, by, bw, bh = cv2.boundingRect(c)
        if bw == 0 or bh / bw > 2.5 or bw / max(bh, 1) > 3.0:
            continue
        m = cv2.moments(c)
        if m["m00"] <= 0:
            continue
        cx = int(m["m10"] / m["m00"])
        cy = int(m["m01"] / m["m00"])
        blobs.append(FlowerBlob(cx, cy, int(area), bx, by, bw, bh))

    blobs.sort(key=lambda b: b.cy, reverse=True)
    return blobs


def steering_hint(
    frame: np.ndarray,
    dead_zone: float = 0.15,
) -> tuple[str, float]:
    """Return a steering hint based on visible flowers.

    Returns ``("left", magnitude)``, ``("right", magnitude)``,
    ``("forward", 0)`` if flowers are centered, or
    ``("none", 0)`` if no flowers are visible.

    *magnitude* is 0-1, representing how far off-center the flowers are.
    """
    blobs = scan_for_flowers(frame)
    if not blobs:
        return ("none", 0.0)

    _h, w = frame.shape[:2]
    mid_x = w / 2.0

    total_weight = 0.0
    weighted_x = 0.0
    for blob in blobs:
        weight = blob.area
        weighted_x += blob.cx * weight
        total_weight += weight

    avg_x = weighted_x / total_weight
    offset = (avg_x - mid_x) / mid_x  # -1 (far left) to +1 (far right)

    if abs(offset) < dead_zone:
        return ("forward", 0.0)
    if offset < 0:
        return ("left", min(abs(offset), 1.0))
    return ("right", min(offset, 1.0))


def debug_annotate(frame: np.ndarray, direction: str, magnitude: float) -> np.ndarray:
    """Draw detected blobs, exclusion zone, and steering arrow on a copy."""
    vis = frame.copy()
    h, w = vis.shape[:2]

    # Draw scan zone boundary (blue dashed)
    sz_x0, sz_x1 = int(w * 0.05), int(w * 0.95)
    sz_y0, sz_y1 = int(h * 0.28), int(h * 0.75)
    cv2.rectangle(vis, (sz_x0, sz_y0), (sz_x1, sz_y1), (255, 150, 0), 1)

    # Draw character exclusion zone
    cx0, cx1 = int(w * 0.40), int(w * 0.60)
    cy0, cy1 = int(h * 0.35), int(h * 0.85)
    cv2.rectangle(vis, (cx0, cy0), (cx1, cy1), (0, 0, 255), 2)
    cv2.putText(
        vis, "EXCL", (cx0 + 4, cy0 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2
    )

    blobs = scan_for_flowers(frame)
    for b in blobs:
        cv2.rectangle(
            vis,
            (b.bbox_x, b.bbox_y),
            (b.bbox_x + b.bbox_w, b.bbox_y + b.bbox_h),
            (0, 255, 0),
            2,
        )
        cv2.circle(vis, (b.cx, b.cy), 6, (0, 255, 255), -1)
        cv2.putText(
            vis,
            str(b.area),
            (b.bbox_x, b.bbox_y - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            1,
        )

    mid_x = w // 2
    label = (
        f"{direction} ({magnitude:.2f})"
        if direction in ("left", "right")
        else direction
    )
    color = {
        "left": (255, 200, 0),
        "right": (255, 200, 0),
        "forward": (0, 255, 0),
        "none": (0, 0, 255),
    }.get(direction, (255, 255, 255))
    cv2.putText(vis, label, (mid_x - 80, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 3)

    return vis
