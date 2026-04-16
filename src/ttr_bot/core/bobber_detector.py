"""Bobber detection via frame differencing.

Compares before-cast and after-cast frames to locate the bobber
landing position inside the pond region.
"""

from collections.abc import Sequence

import cv2
import numpy as np

from ttr_bot.utils.logger import log

_BOBBER_MIN_AREA = 50
_BOBBER_MAX_AREA = 5000


def _debug_bobber_frames(
    frames: tuple[np.ndarray, np.ndarray, np.ndarray],
    contours: Sequence,
    roi: tuple[int, int, int, int],
    drag_label: str,
) -> None:
    """Write before/after/diff debug images for bobber detection."""
    from ttr_bot.utils import debug_frames as dbg

    before, after, thresh = frames
    x1, y1, x2, y2 = roi
    rect_ann = {
        "type": "rect",
        "pt1": (x1, y1),
        "pt2": (x2, y2),
        "color": (0, 255, 0),
        "thickness": 1,
    }
    dbg.save(before, f"cal_{drag_label}_before", annotations=[rect_ann])
    dbg.save(after, f"cal_{drag_label}_after", annotations=[rect_ann])

    diff_vis = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
    full_diff = np.zeros_like(before)
    full_diff[y1:y2, x1:x2] = diff_vis
    diff_anns: list[dict] = [rect_ann]
    for c in contours:
        area_c = cv2.contourArea(c)
        m = cv2.moments(c)
        if m["m00"] > 0:
            bx = int(m["m10"] / m["m00"]) + x1
            by = int(m["m01"] / m["m00"]) + y1
            diff_anns.append(
                {"type": "circle", "center": (bx, by), "radius": 8, "color": (0, 255, 255)}
            )
            diff_anns.append(
                {
                    "type": "text",
                    "pos": (bx + 10, by),
                    "text": f"a={area_c}",
                    "color": (0, 255, 255),
                    "thickness": 1,
                }
            )
    dbg.save(full_diff, f"cal_{drag_label}_diff", annotations=diff_anns)


def detect_bobber(
    before: np.ndarray,
    after: np.ndarray,
    pond_rect: tuple[int, int, int, int],
    *,
    drag_label: str = "",
) -> tuple[int, int] | None:
    """Detect the bobber landing position via frame differencing.

    Compares before-cast and after-cast frames within the pond region.
    The bobber is the largest bright new blob in the diff.
    Returns (cx, cy) in full-frame retina coordinates, or None.
    """
    from ttr_bot.utils import debug_frames as dbg

    if before.shape != after.shape:
        log.warning("detect_bobber: frame shape mismatch")
        return None

    gray_before = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    gray_after = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)

    pond_x, pond_y, pond_w, pond_h = pond_rect
    y1, y2 = pond_y, pond_y + pond_h
    x1, x2 = pond_x, pond_x + pond_w
    h, w = gray_before.shape
    y1, y2 = max(0, y1), min(h, y2)
    x1, x2 = max(0, x1), min(w, x2)

    diff = cv2.absdiff(gray_after[y1:y2, x1:x2], gray_before[y1:y2, x1:x2])
    diff = cv2.GaussianBlur(diff, (7, 7), 0)
    _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    thresh = cv2.dilate(thresh, kernel, iterations=2)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if dbg.is_enabled():
        _debug_bobber_frames((before, after, thresh), contours, (x1, y1, x2, y2), drag_label)

    if not contours:
        log.warning("detect_bobber: no changed blobs found in pond region")
        return None

    valid = [c for c in contours if _BOBBER_MIN_AREA <= cv2.contourArea(c) <= _BOBBER_MAX_AREA]
    if not valid:
        areas = sorted([int(cv2.contourArea(c)) for c in contours], reverse=True)[:5]
        log.warning(
            "detect_bobber: no blobs in area range %d-%d (top areas: %s)",
            _BOBBER_MIN_AREA,
            _BOBBER_MAX_AREA,
            areas,
        )
        return None

    best = max(valid, key=cv2.contourArea)
    area = cv2.contourArea(best)
    mom = cv2.moments(best)
    if mom["m00"] == 0:
        return None
    cx = int(mom["m10"] / mom["m00"]) + x1
    cy = int(mom["m01"] / mom["m00"]) + y1

    if dbg.is_enabled():
        dbg.save(
            after,
            f"cal_{drag_label}_landing",
            annotations=[
                {
                    "type": "circle",
                    "center": (cx, cy),
                    "radius": 15,
                    "color": (0, 0, 255),
                    "thickness": 3,
                },
                {
                    "type": "text",
                    "pos": (cx + 18, cy),
                    "text": f"bobber ({cx},{cy}) area={area}",
                    "color": (0, 0, 255),
                    "thickness": 2,
                },
            ],
        )

    log.info("detect_bobber: landing at (%d,%d) blob_area=%d", cx, cy, area)
    return cx, cy
